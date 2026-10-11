"""Overview: KPI strip, the network map, sensor health, the priority queue, rainfall and flood-prone points."""

from __future__ import annotations

from nicegui import ui

from drainwatch import service
from ui import charts
from ui import components as c
from ui.drawer import DrainDrawer
from ui.layout import shell
from ui.map_view import MapLayers, MapState, NetworkMap, legend


def _greeting(hour: int) -> str:
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def rain_legend() -> None:
    with ui.row().classes("gap-x-3 gap-y-1 dw-xs dw-muted mt-2"):
        for var, text, opacity in (
            ("--accent", "Observed", 1),
            ("--warning", "Heavy, 24 mm/h or more", 1),
            ("--accent", "Scenario forecast", 0.28),
        ):
            with ui.row().classes("items-center gap-1 no-wrap"):
                ui.element("span").classes("dw-legend-dot").style(
                    f"background:var({var});opacity:{opacity};border-radius:2px"
                )
                ui.label(text)


@ui.page("/")
async def overview_page() -> None:
    page = await shell("overview", "Overview")
    if page is None:
        return
    first_render = {"kpi": True}
    network: dict[str, NetworkMap] = {}
    drawer = DrainDrawer(page, on_change=lambda d: network["map"].select(d))

    with ui.element("main").classes("dw-page w-full"):

        @ui.refreshable
        def heading() -> None:
            st = service.state()
            with ui.element("div").classes("dw-page-head"):
                with ui.column().classes("gap-1"):
                    ui.html(f'<h1 class="dw-h1">{_greeting(st.sim_time.hour)}</h1>', sanitize=False)
                    ui.label(f"{st.sim_time:%A %d %B %Y, %H:%M}, simulated storm time").classes("dw-muted")

        heading()

        @ui.refreshable
        def kpis() -> None:
            k = service.kpis(page.zone_id)
            count_up = first_render["kpi"] and not page.reduced_motion
            first_render["kpi"] = False
            with ui.element("div").classes("grid grid-cols-2 lg:grid-cols-4 gap-4 w-full"):
                sensors = service.sensor_health(page.zone_id)["total"]
                c.kpi(
                    "Drains monitored", k["monitored"], note=f"{sensors} with a water-level sensor", count_up=count_up
                )
                c.kpi(
                    "Critical now",
                    k["critical"],
                    tone="critical" if k["critical"] else None,
                    note="Priority score 75 or more",
                    count_up=count_up,
                )
                c.kpi(
                    "Likely blocked",
                    k["likely_blocked"],
                    tone="high" if k["likely_blocked"] else None,
                    note="High level, nearby drains normal",
                    count_up=count_up,
                )
                c.kpi(
                    "Inspections done", k["inspections"], unit=f"of {k['target']}", note="This shift", count_up=count_up
                )

        kpis()

        with ui.element("div").classes("grid gap-4 w-full mt-4 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px]"):
            # ---------------- map
            with (
                ui.element("section")
                .classes("dw-card dw-hud relative p-0 overflow-hidden h-[600px]")
                .props('aria-label="Drain network map"')
            ):
                network["map"] = NetworkMap(
                    page.palette,
                    lambda: page.reduced_motion,
                    on_select=drawer.open,
                    state=MapState(layers=MapLayers(labels=4)),
                )
                with ui.element("div").classes("dw-map-overlay left-3 bottom-3"):
                    legend("priority", service.thresholds().warning, service.thresholds().critical)
                with ui.element("div").classes("dw-map-overlay right-3 top-3"):
                    with (
                        ui.link(target="/map")
                        .classes("flex items-center gap-1 px-3 py-2 no-underline dw-small font-semibold")
                        .style("color:var(--accent-ink)")
                    ):
                        ui.label("Open full map")
                        ui.icon("open_in_full").classes("text-base")

            # ---------------- right rail
            with ui.column().classes("gap-4 min-w-0"):
                with ui.element("section").classes("dw-card dw-card-pad w-full"):

                    @ui.refreshable
                    def sensors() -> None:
                        h = service.sensor_health(page.zone_id)
                        c.card_title(f"Sensor health, {h['total']} sensors")
                        with ui.row().classes("justify-between w-full mt-3 no-wrap"):
                            c.ring(h["normal"], h["total"], "--normal", "Normal")
                            c.ring(h["warning"], h["total"], "--warning", "Warning")
                            c.ring(h["alarm"], h["total"], "--critical", "Alarm")
                        ui.label(
                            f"{h['faulty']} not reporting properly. {h['rain_gauges']} rain gauges reporting."
                        ).classes("dw-xs dw-muted mt-2")

                    sensors()

                with ui.element("section").classes("dw-card dw-card-pad w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        c.card_title("Priority queue")
                        ui.link("See all", "/queue").classes("dw-small font-semibold no-underline").style(
                            "color:var(--accent-ink)"
                        )

                    @ui.refreshable
                    def queue() -> None:
                        rows = service.drain_rows(page.zone_id)[:5]
                        with ui.column().classes("w-full gap-2 mt-3"):
                            for r in rows:
                                sc = r.score
                                with (
                                    ui.element("button")
                                    .classes("dw-row-item w-full text-left")
                                    .props(f'type="button" aria-label="Open {r.info.id}"')
                                    .on("click", lambda d=r.info.id: drawer.open(d))
                                ):
                                    with ui.row().classes("items-center gap-3 no-wrap w-full"):
                                        with ui.element("div").classes("w-[96px] shrink-0"):
                                            c.band_badge(sc.band.value, sc.score, solid=True)
                                        with ui.column().classes("gap-0 min-w-0 flex-1"):
                                            ui.label(f"{r.info.id} {r.info.name.split(',')[0]}").classes(
                                                "font-semibold text-[13.5px] truncate w-full"
                                            )
                                            ui.label(sc.label.value).classes("dw-xs dw-muted truncate w-full")

                    queue()

        with ui.element("div").classes("grid gap-4 w-full mt-4 grid-cols-1 md:grid-cols-2"):
            with ui.element("section").classes("dw-card dw-card-pad w-full"):
                c.card_title("Rainfall, mm per 10 min", "City average across the six-hour storm")
                rain_legend()
                rain_chart = ui.echart(
                    charts.rainfall(service.rainfall_series(), page.palette(), page.reduced_motion)
                ).classes("w-full h-[190px]")

            with ui.element("section").classes("dw-card dw-card-pad w-full"):
                c.card_title("Water level at flood-prone points", "Percent of drain depth")

                @ui.refreshable
                def watch_points() -> None:
                    with ui.column().classes("w-full gap-3 mt-3"):
                        for info, sc in service.watch_points():
                            label = info.site_name or info.name.split(",")[0]
                            ok = sc is not None and sc.sensor_ok and sc.fill_pct is not None
                            with (
                                ui.element("button")
                                .classes("w-full text-left flex flex-col gap-1")
                                .props(f'type="button" aria-label="Open {info.id}, {label}"')
                                .on("click", lambda d=info.id: drawer.open(d))
                            ):
                                with ui.row().classes("justify-between w-full items-center"):
                                    ui.label(label).classes("dw-small font-medium")
                                    if ok:
                                        with ui.row().classes("items-center gap-1 no-wrap"):
                                            ui.icon(c.FILL_ICON[sc.fill_status.value]).classes("text-sm").style(
                                                f"color:var({c.fill_var(sc.fill_status.value)})"
                                            )
                                            ui.label(
                                                f"{c.FILL_TEXT[sc.fill_status.value]}, {sc.fill_pct:.0f}%"
                                            ).classes("dw-small")
                                    else:
                                        ui.label("No reading").classes("dw-small dw-muted")
                                c.meter(
                                    sc.fill_pct if ok else 0,
                                    c.fill_var(sc.fill_status.value) if ok else "--unknown",
                                    f"{label} fill",
                                )

                watch_points()

        # ---------------- recent field reports
        with ui.element("section").classes("dw-card dw-card-pad w-full mt-4"):
            with ui.row().classes("items-center justify-between w-full"):
                c.card_title("Recent field reports", "Citizen calls, patrols and crews during this storm")
                ui.link("All incidents", "/incidents").classes("dw-small font-semibold no-underline").style(
                    "color:var(--accent-ink)"
                )

            @ui.refreshable
            def reports() -> None:
                rows = service.incidents()
                if page.zone_id:
                    rows = [r for r in rows if r.drain.zone_id == page.zone_id]
                rows = rows[:6]
                if not rows:
                    with ui.element("div").classes("mt-3 w-full"):
                        c.empty_state(
                            "No reports yet. They arrive as the storm runs, or log one with Log incident.", "campaign"
                        )
                    return
                now = service.now()
                with ui.element("div").classes("w-full overflow-x-auto mt-3"):
                    with ui.element("table").classes("w-full text-left dw-small"):
                        with ui.element("thead"):
                            with ui.element("tr").classes("dw-muted"):
                                for h in ("Report", "Drain", "Issue", "Severity", "Source", "Status", "Received"):
                                    with ui.element("th").classes("py-2 pr-4 font-semibold").props('scope="col"'):
                                        ui.label(h)
                        with ui.element("tbody"):
                            for row in rows:
                                r = row.report
                                with (
                                    ui.element("tr")
                                    .classes("cursor-pointer dw-tr")
                                    .on("click", lambda d=r.drain_id: drawer.open(d))
                                ):
                                    with ui.element("td").classes("py-2 pr-4"):
                                        ui.label(r.id).classes("dw-mono")
                                    with ui.element("td").classes("py-2 pr-4"):
                                        ui.label(f"{row.drain.id} {row.drain.name.split(',')[0]}")
                                    with ui.element("td").classes("py-2 pr-4"):
                                        ui.label(r.type.value)
                                    with ui.element("td").classes("py-2 pr-4"):
                                        c.severity_badge(r.severity.value)
                                    with ui.element("td").classes("py-2 pr-4"):
                                        ui.label(f"{r.source.value}, {r.reporter}")
                                    with ui.element("td").classes("py-2 pr-4"):
                                        c.badge(
                                            c.REPORT_STATUS_TEXT[r.status.value], c.REPORT_STATUS_TONE[r.status.value]
                                        )
                                    with ui.element("td").classes("py-2 pr-4 whitespace-nowrap"):
                                        ui.label(c.ago(r.ts, now)).classes("dw-muted")

            reports()

    def update_rain() -> None:
        rain_chart.options.clear()
        rain_chart.options.update(charts.rainfall(service.rainfall_series(), page.palette(), page.reduced_motion))
        rain_chart.update()

    def live() -> None:
        heading.refresh()
        kpis.refresh()
        update_rain()
        watch_points.refresh()
        network["map"].state.zone_id = page.zone_id
        network["map"].refresh()
        sensors.refresh()
        queue.refresh()
        reports.refresh()

    def retheme() -> None:
        update_rain()
        network["map"].restyle()

    page.on_live(live)
    page.on_theme(retheme)
