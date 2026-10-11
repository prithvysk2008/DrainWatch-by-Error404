"""Control room wall: a full-screen, always-dark view for a large display. Refreshes itself as the storm runs."""

from __future__ import annotations

from nicegui import ui

from drainwatch import service
from ui import charts
from ui import components as c
from ui.layout import Page, detect_client, head, require_user
from ui.map_view import MapLayers, MapState, NetworkMap, legend

THREAT_VAR = {1: "--normal", 2: "--info", 3: "--warning", 4: "--critical"}
THREAT_ICON = {1: "check_circle", 2: "info", 3: "warning", 4: "error"}


def panel(title: str):
    """A wall panel with its title. Use as a context manager."""
    el = ui.element("section").classes("dw-wall-panel flex flex-col min-h-0")
    with el:
        ui.label(title).classes("dw-wall-title")
    return el


@ui.page("/wall")
async def wall_page() -> None:
    user = require_user("operator")
    if user is None:
        return
    head()
    _, reduced = await detect_client("dark")
    ui.dark_mode(True)
    ui.page_title("Control room wall | Drain Watch")
    page = Page(user["username"], user["display_name"], True, reduced)

    ui.query(".nicegui-content").style("padding:0;gap:0")
    with ui.element("div").classes("dw-wall w-full"):
        # ---------------------------------------------------------------- header
        with ui.element("header").classes("dw-wall-head"):

            @ui.refreshable
            def clock() -> None:
                st = service.state()
                with ui.row().classes("items-baseline gap-4 no-wrap"):
                    ui.label(f"{st.sim_time:%d %b %Y}").classes("dw-wall-clock")
                    ui.label(f"{st.sim_time:%A}").classes("dw-wall-clock dw-wall-dim")
                    ui.label(f"{st.sim_time:%H:%M}").classes("dw-wall-clock")

            clock()
            with ui.column().classes("items-center gap-0"):
                ui.label("Rivermere drainage, live overview").classes("dw-wall-name")
                ui.label("Simulated data. Ranks drains by inspection priority.").classes("dw-wall-sub")

            @ui.refreshable
            def status() -> None:
                level, name = service.threat()
                st = service.state()
                with ui.row().classes("items-center gap-5 no-wrap"):
                    with ui.column().classes("gap-0 items-end"):
                        ui.label("Flood threat").classes("dw-wall-sub")
                        with ui.row().classes("items-center gap-1 no-wrap"):
                            ui.icon(THREAT_ICON[level]).style(f"color:var({THREAT_VAR[level]})")
                            ui.label(f"Level {['I', 'II', 'III', 'IV'][level - 1]}, {name}").classes("dw-wall-strong")
                    with ui.column().classes("gap-0 items-end"):
                        ui.label(f"{st.scenario}, step {st.step + 1} of {st.total_steps}").classes("dw-wall-sub")
                        ui.label("Playing" if st.playing else "Paused").classes("dw-wall-strong")
                    c.button(icon="close", on_click=lambda: ui.navigate.to("/")).classes("dw-icon-btn").props(
                        'flat aria-label="Leave wall mode"'
                    ).tooltip("Leave wall mode")

            status()

        # ---------------------------------------------------------------- ticker
        @ui.refreshable
        def ticker() -> None:
            banner = service.storm_banner()
            latest = service.notifications()[:1]
            with ui.element("div").classes("dw-wall-ticker").props('role="status"'):
                ui.icon("campaign").classes("text-xl").style("color:var(--warning)")
                ui.label(banner[1] if banner else "No storm running. Rankings refresh every simulated ten minutes.")
                if latest:
                    n = latest[0]
                    ui.space()
                    ui.label(f"{n.ts:%H:%M}  {n.title}. {n.body}").classes("dw-wall-dim truncate max-w-[45%]")

        ticker()

        # ---------------------------------------------------------------- body
        with ui.element("div").classes("dw-wall-grid"):
            with ui.column().classes("gap-3 min-h-0 min-w-0 h-full items-stretch no-wrap"):
                with panel("Rainfall now"):

                    @ui.refreshable
                    def rain_now() -> None:
                        rate = service.city_rain_mm_h()
                        with ui.row().classes("items-baseline gap-2 mt-1"):
                            ui.label(f"{rate:.1f}").classes("dw-wall-big")
                            ui.label("mm per hour, city average").classes("dw-wall-sub")

                    rain_now()
                    rain_chart = ui.echart(
                        charts.rainfall(service.rainfall_series(), page.palette(), page.reduced_motion)
                    ).classes("w-full h-[180px]")
                with panel("Flood-prone points").classes("grow"):

                    @ui.refreshable
                    def points() -> None:
                        with ui.column().classes("w-full gap-3 mt-2"):
                            for info, sc in service.watch_points():
                                ok = sc is not None and sc.sensor_ok and sc.fill_pct is not None
                                label = info.site_name or info.name.split(",")[0]
                                with ui.row().classes("justify-between w-full items-center"):
                                    ui.label(label).classes("dw-wall-text")
                                    if ok:
                                        with ui.row().classes("items-center gap-1 no-wrap"):
                                            ui.icon(c.FILL_ICON[sc.fill_status.value]).style(
                                                f"color:var({c.fill_var(sc.fill_status.value)})"
                                            )
                                            ui.label(
                                                f"{c.FILL_TEXT[sc.fill_status.value]}, {sc.fill_pct:.0f}%"
                                            ).classes("dw-wall-text")
                                    else:
                                        ui.label("No reading").classes("dw-wall-text dw-wall-dim")
                                c.meter(
                                    sc.fill_pct if ok else 0,
                                    c.fill_var(sc.fill_status.value) if ok else "--unknown",
                                    f"{label} fill",
                                )

                    points()

            with ui.column().classes("gap-3 min-h-0 min-w-0 h-full items-stretch no-wrap"):

                @ui.refreshable
                def kpis() -> None:
                    k = service.kpis()
                    with ui.element("div").classes("grid grid-cols-4 gap-3 w-full"):
                        for label, value, tone in (
                            ("Drains monitored", k["monitored"], None),
                            ("Critical now", k["critical"], "critical" if k["critical"] else None),
                            ("Likely blocked", k["likely_blocked"], "high" if k["likely_blocked"] else None),
                            ("Inspections this shift", k["inspections"], None),
                        ):
                            with ui.element("div").classes("dw-wall-panel py-3"):
                                ui.label(label).classes("dw-wall-sub")
                                ui.label(str(value)).classes("dw-wall-big" + (f" is-{tone}" if tone else ""))

                kpis()
                with (
                    ui.element("section")
                    .classes("dw-wall-panel dw-hud relative grow min-h-0 overflow-hidden")
                    .style("padding:0")
                ):
                    wall_map = NetworkMap(
                        page.palette, lambda: page.reduced_motion, state=MapState(layers=MapLayers(labels=6))
                    )
                    with ui.element("div").classes("dw-map-overlay left-3 bottom-3"):
                        th = service.thresholds()
                        legend("priority", th.warning, th.critical)

            with ui.column().classes("gap-3 min-h-0 min-w-0 h-full items-stretch no-wrap"):
                with panel("Sensor health"):

                    @ui.refreshable
                    def rings() -> None:
                        h = service.sensor_health()
                        with ui.row().classes("justify-between w-full mt-2 no-wrap"):
                            c.ring(h["normal"], h["total"], "--normal", "Normal", size=104)
                            c.ring(h["warning"], h["total"], "--warning", "Warning", size=104)
                            c.ring(h["alarm"], h["total"], "--critical", "Alarm", size=104)
                        ui.label(f"{h['total']} water-level sensors. {h['faulty']} not reporting properly.").classes(
                            "dw-wall-sub mt-1"
                        )

                    rings()
                with panel("Inspect first").classes("grow"):

                    @ui.refreshable
                    def alerts() -> None:
                        rows = service.drain_rows()[:7]
                        with ui.column().classes("w-full gap-2 mt-2 items-stretch"):
                            for r in rows:
                                sc = r.score
                                with ui.element("div").classes("dw-wall-alert min-w-0"):
                                    with ui.row().classes("items-center justify-between w-full no-wrap"):
                                        ui.label(f"{r.rank}. {r.info.id}").classes("dw-wall-strong dw-mono")
                                        c.band_badge(sc.band.value, sc.score, solid=True)
                                    ui.label(r.info.name).classes("dw-wall-text truncate w-full")
                                    with ui.row().classes("items-center justify-between w-full no-wrap"):
                                        ui.label(sc.label.value).classes("dw-wall-sub truncate min-w-0")
                                        crew = (
                                            "Crew sent"
                                            if r.open_order and r.open_order.crew_id
                                            else ("Order open" if r.open_order else "No crew yet")
                                        )
                                        ui.label(crew).classes("dw-wall-sub whitespace-nowrap")

                    alerts()

    def live() -> None:
        clock.refresh()
        status.refresh()
        ticker.refresh()
        rain_now.refresh()
        rain_chart.options.clear()
        rain_chart.options.update(charts.rainfall(service.rainfall_series(), page.palette(), page.reduced_motion))
        rain_chart.update()
        points.refresh()
        kpis.refresh()
        wall_map.refresh()
        rings.refresh()
        alerts.refresh()

    def poll() -> None:
        v = service.version()
        if v != page.version:
            page.version = v
            live()

    page.version = service.version()
    ui.timer(0.5, poll)
