"""Live monitoring map: the full network with search, status filters, layers and the detail drawer."""

from __future__ import annotations

from nicegui import ui

from drainwatch import service
from ui import components as c
from ui.drawer import DrainDrawer
from ui.layout import shell
from ui.map_view import MapState, NetworkMap, legend

FILTERS = {
    "priority": [("all", "All"), ("critical", "Critical"), ("high", "High"), ("medium", "Medium"), ("low", "Low")],
    "level": [("all", "All"), ("critical", "Critical"), ("warning", "Warning"), ("normal", "Normal")],
}


@ui.page("/map")
async def map_page() -> None:
    page = await shell("map", "Live monitoring map")
    if page is None:
        return
    holder: dict[str, NetworkMap] = {}
    drawer = DrainDrawer(page, on_change=lambda d: holder["map"].select(d))
    state = MapState(color_by="level", zone_id=page.zone_id)

    with ui.element("main").classes("dw-page w-full"):
        with ui.element("div").classes("dw-page-head"):
            with ui.column().classes("gap-1"):
                ui.html('<h1 class="dw-h1">Live monitoring map</h1>', sanitize=False)
                ui.label(
                    "Schematic map of Rivermere's drain network. Scroll to zoom, drag to pan, select a drain "
                    "for details."
                ).classes("dw-muted")

        toolbar_slot = ui.element("div").classes("w-full mb-3")
        with (
            ui.element("section")
            .classes("dw-card dw-hud relative p-0 overflow-hidden w-full h-[calc(100vh-290px)] min-h-[560px]")
            .props('aria-label="Drain map"')
        ):
            holder["map"] = NetworkMap(page.palette, lambda: page.reduced_motion, on_select=drawer.open, state=state)

            with ui.element("div").classes("dw-card p-2 flex flex-wrap items-center gap-2 w-full") as toolbar:
                search = (
                    ui.input(placeholder="Drain ID or street")
                    .props('dense outlined clearable aria-label="Search drains"')
                    .classes("w-[220px]")
                )
                with search.add_slot("prepend"):
                    ui.icon("search").classes("text-lg")

                def on_search() -> None:
                    state.search = (search.value or "").strip()
                    holder["map"].refresh()
                    matches = service.search(state.search, 1) if state.search else []
                    if len(state.search) >= 4 and matches and matches[0].id.lower() == state.search.lower():
                        drawer.open(matches[0].id)

                search.on("update:model-value", on_search, throttle=0.3)

                @ui.refreshable
                def filter_chips() -> None:
                    with ui.element("div").classes("dw-seg").props('role="group" aria-label="Status filter"'):
                        for key, text in FILTERS[state.color_by]:
                            c.button(text, on_click=lambda k=key: set_filter(k)).props(
                                "flat dense no-caps" + (' aria-pressed="true"' if state.status_filter == key else "")
                            ).classes("is-on" if state.status_filter == key else "")

                filter_chips()

                def set_filter(key: str) -> None:
                    state.status_filter = key
                    filter_chips.refresh()
                    holder["map"].refresh()

                with ui.element("div").classes("dw-seg").props('role="group" aria-label="Colour drains by"'):
                    by_priority = c.button("Priority", on_click=lambda: set_mode("priority")).props(
                        "flat dense no-caps"
                    )
                    by_level = c.button("Water level", on_click=lambda: set_mode("level")).props("flat dense no-caps")

                def paint_mode() -> None:
                    by_priority.classes(
                        add="is-on" if state.color_by == "priority" else "",
                        remove="" if state.color_by == "priority" else "is-on",
                    )
                    by_level.classes(
                        add="is-on" if state.color_by == "level" else "",
                        remove="" if state.color_by == "level" else "is-on",
                    )

                def set_mode(mode: str) -> None:
                    state.color_by = mode
                    state.status_filter = "all"
                    paint_mode()
                    filter_chips.refresh()
                    legend_box.refresh()
                    holder["map"].refresh()

                paint_mode()

                with c.button("Layers", icon="layers").classes("dw-btn-secondary").props("unelevated no-caps dense"):
                    with ui.menu().classes("p-3 min-w-[220px]"):
                        ui.label("Show on map").classes("dw-section-title mb-1")
                        for attr, text in (
                            ("flow", "Flow direction (dark mode)"),
                            ("zones", "Zone boundaries"),
                            ("reports", "Citizen reports"),
                            ("sensors", "Sensor nodes as squares"),
                        ):
                            ui.checkbox(
                                text,
                                value=getattr(state.layers, attr),
                                on_change=lambda e, a=attr: (
                                    setattr(state.layers, a, e.value),
                                    holder["map"].refresh(),
                                ),
                            )

                c.button("Reset view", icon="center_focus_strong", on_click=lambda: holder["map"].reset_view()).classes(
                    "dw-btn-secondary"
                ).props("unelevated no-caps dense")

            with ui.element("div").classes("dw-map-overlay left-3 bottom-3"):

                @ui.refreshable
                def legend_box() -> None:
                    th = service.thresholds()
                    legend(state.color_by, th.warning, th.critical)

                legend_box()
        toolbar.move(toolbar_slot)

    def live() -> None:
        state.zone_id = page.zone_id
        holder["map"].refresh()
        legend_box.refresh()

    page.on_live(live)
    page.on_theme(holder["map"].restyle)
