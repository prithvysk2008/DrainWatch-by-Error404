"""Analytics and hotspots: storm response, hotspots, root causes, time to resolve, and the validation panel."""

from __future__ import annotations

from nicegui import app, ui

from drainwatch import service
from ui import charts
from ui import components as c
from ui.layout import shell


@ui.page("/analytics")
async def analytics_page() -> None:
    page = await shell("analytics", "Analytics and hotspots")
    if page is None:
        return
    window = {"value": app.storage.user.get("analytics_window", service.WINDOWS[0])}
    charts_by_key: dict[str, ui.echart] = {}

    with ui.element("main").classes("dw-page w-full"):
        with ui.element("div").classes("dw-page-head"):
            with ui.column().classes("gap-1 max-w-[760px]"):
                ui.html('<h1 class="dw-h1">Analytics and hotspots</h1>', sanitize=False)
                ui.label(
                    "How the network responds to rain, where blockages recur and how fast crews clear them. "
                    "Every figure comes from simulated data."
                ).classes("dw-muted")
            ui.select(
                list(service.WINDOWS), value=window["value"], label="Timeline", on_change=lambda e: set_window(e.value)
            ).props("outlined dense options-dense").classes("min-w-[260px]")

        # ---------------- storm response
        with ui.element("section").classes("dw-card dw-card-pad w-full"):

            @ui.refreshable
            def response_head() -> None:
                data = service.analytics_data(window["value"], page.zone_id)
                with ui.row().classes("items-start justify-between w-full"):
                    c.card_title(
                        "Water level against rainfall, this storm",
                        "Average fill of drains with a working sensor, and city rainfall, on one time axis",
                    )
                    lag = data["lag_min"]
                    c.badge(
                        f"Response lag about {lag} min" if lag is not None else "Lag needs more of the storm",
                        "info",
                        "schedule",
                    )

            response_head()
            with ui.element("div").classes("grid grid-cols-1 w-full gap-0 mt-2"):
                charts_by_key["fill"] = ui.echart({}).classes("w-full h-[200px]")
                charts_by_key["rain"] = ui.echart({}).classes("w-full h-[140px]")
            with ui.row().classes("gap-4 dw-xs dw-muted"):
                for var, text in (
                    ("--accent", "Average fill, percent"),
                    ("--unknown", "Expected without faults"),
                    ("--info", "Rainfall, mm per hour"),
                ):
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        ui.element("span").classes("dw-legend-dot").style(f"background:var({var})")
                        ui.label(text)

        with ui.element("div").classes("grid gap-4 w-full mt-4 grid-cols-1 lg:grid-cols-3"):
            with ui.element("section").classes("dw-card dw-card-pad"):

                @ui.refreshable
                def hotspot_head() -> None:
                    data = service.analytics_data(window["value"], page.zone_id)
                    top = data["hotspots"][0][0] if data["hotspots"] else "none"
                    c.card_title("Blocked hotspots by ward", f"Reports in the period. Top ward: {top}")

                hotspot_head()
                charts_by_key["hotspots"] = ui.echart({}).classes("w-full h-[260px] mt-2")
            with ui.element("section").classes("dw-card dw-card-pad"):
                c.card_title("Blockage root causes", "What crews found on inspection")
                charts_by_key["causes"] = ui.echart({}).classes("w-full h-[260px] mt-2")
            with ui.element("section").classes("dw-card dw-card-pad"):

                @ui.refreshable
                def mttr_head() -> None:
                    data = service.analytics_data(window["value"], page.zone_id)
                    values = [v for _, v in data["mttr"]]
                    avg = f"Average {sum(values) / len(values):.0f} min" if values else "No resolved reports"
                    c.card_title("Mean time to resolve by zone", f"From report to clearance. {avg}")

                mttr_head()
                charts_by_key["mttr"] = ui.echart({}).classes("w-full h-[260px] mt-2")

        # ---------------- validation and impact
        with ui.element("div").classes("grid gap-4 w-full mt-4 grid-cols-1 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]"):
            with ui.element("section").classes("dw-card dw-card-pad").props('aria-labelledby="validation-title"'):
                with ui.row().classes("items-start justify-between w-full gap-3"):
                    with ui.column().classes("gap-0"):
                        ui.label("Validation against the simulation").classes("dw-card-title").props(
                            'id="validation-title"'
                        )
                        ui.label("Simulated data. Shows how the method behaves, not real-world accuracy.").classes(
                            "dw-small font-semibold mt-1"
                        ).style("color:var(--warning-ink)")

                @ui.refreshable
                def validation() -> None:
                    v = service.validation()
                    if v["truth_count"] == 0:
                        c.empty_state("No planted faults have started yet. Run the storm for a few steps.", "science")
                        return
                    ui.label(
                        f"At step {v['step'] + 1}, the simulation has {v['truth_count']} drains with a real problem: "
                        "a planted blockage, or a place in the congested trunk section. "
                        "The ranking never sees this list."
                    ).classes("dw-small dw-muted mt-2")
                    with ui.element("div").classes(
                        "grid grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)] gap-4 mt-3 items-center"
                    ):
                        with ui.column().classes("gap-3"):
                            for label, value, base in (
                                ("Precision at 10", v["precision_at_10"], v["random_precision_at_10"]),
                                ("Recall at 20", v["recall_at_20"], v["random_recall_at_20"]),
                            ):
                                with ui.column().classes("gap-0"):
                                    ui.label(label).classes("dw-small dw-muted")
                                    with ui.row().classes("items-baseline gap-2"):
                                        ui.label(f"{value:.2f}").classes("dw-kpi-value")
                                        ui.label(f"random {base:.2f}").classes("dw-small dw-muted")
                        ui.echart(
                            charts.validation_bars(
                                (v["precision_at_10"], v["recall_at_20"]),
                                (v["random_precision_at_10"], v["random_recall_at_20"]),
                                page.palette(),
                            )
                        ).classes("w-full h-[220px]")
                    ui.label(
                        "Precision at 10: share of the top 10 ranked drains that truly had a problem. "
                        "Recall at 20: share of all true problems found in the top 20."
                    ).classes("dw-xs dw-muted")

                validation()

            with ui.element("section").classes("dw-card dw-card-pad"):
                c.card_title("Impact this storm", "Work done since the storm started")

                @ui.refreshable
                def impact() -> None:
                    i = service.impact()
                    k = service.kpis()
                    items = [
                        ("Work orders opened", str(i["orders_opened"])),
                        ("Work orders cleared", str(i["orders_resolved"])),
                        ("Reports closed", str(i["reports_closed"])),
                        ("Inspections this shift", f"{k['inspections']} of {k['target']}"),
                        (
                            "Median time to clear an order",
                            f"{i['median_minutes']:.0f} min" if i["median_minutes"] is not None else "None cleared yet",
                        ),
                    ]
                    with ui.column().classes("w-full gap-0 mt-3"):
                        for label, value in items:
                            with (
                                ui.row()
                                .classes("justify-between w-full py-2")
                                .style("border-bottom:1px solid var(--border)")
                            ):
                                ui.label(label).classes("dw-small")
                                ui.label(value).classes("dw-small font-semibold dw-tabular")
                    ui.label(
                        "Clearing an order records an inspection and lowers that drain's priority straight away."
                    ).classes("dw-xs dw-muted mt-3")

                impact()

    def draw() -> None:
        p = page.palette()
        data = service.analytics_data(window["value"], page.zone_id)
        options = {
            "fill": charts.time_panel(
                data["times"],
                data["avg_fill"],
                "Average fill",
                "%",
                p,
                p.accent,
                reference=data["expected_fill"],
                show_x=False,
            ),
            "rain": charts.time_panel(data["times"], data["rain_mm_h"], "Rainfall", "mm/h", p, p.info, bars=True),
            "hotspots": charts.hbar([(w, float(n)) for w, n in data["hotspots"]], p),
            "causes": charts.hbar([(name, float(n)) for name, n in data["causes"]], p),
            "mttr": charts.hbar(data["mttr"], p, unit="min"),
        }
        for key, chart in charts_by_key.items():
            chart.options.clear()
            chart.options.update(options[key])
            chart.update()

    def set_window(value: str) -> None:
        window["value"] = value
        app.storage.user["analytics_window"] = value
        refresh_all()

    def refresh_all() -> None:
        draw()
        response_head.refresh()
        hotspot_head.refresh()
        mttr_head.refresh()
        validation.refresh()
        impact.refresh()

    draw()
    page.on_live(refresh_all)
    page.on_theme(refresh_all)
