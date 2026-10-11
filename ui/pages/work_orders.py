"""Crews and work orders: a four-column dispatch board and the crew route planner."""

from __future__ import annotations

from nicegui import ui

from drainwatch import service
from drainwatch.models import Finding, Stage
from ui import components as c
from ui.drawer import DrainDrawer
from ui.layout import Page, shell
from ui.map_view import MapLayers, MapState, NetworkMap

STAGE_ORDER = [Stage.pending, Stage.en_route, Stage.active, Stage.resolved]
STAGE_ICON = {
    Stage.pending: "schedule",
    Stage.en_route: "local_shipping",
    Stage.active: "construction",
    Stage.resolved: "task_alt",
}
NEXT_LABEL = {Stage.pending: "Send crew", Stage.en_route: "Start work", Stage.active: "Mark as cleared"}


def finding_dialog(order_id: str, page: Page, done) -> None:
    """Clearing an order records an inspection, so ask what the crew found."""
    with ui.dialog() as dialog, ui.card().classes("p-5 w-[420px] max-w-[95vw]"):
        ui.label(f"Clear {order_id}").classes("dw-card-title")
        ui.label(
            "Record what the crew found. This adds an inspection to the drain's history and lowers its priority."
        ).classes("dw-small dw-muted mt-1")
        choice = ui.radio({f.name: f.value for f in Finding}, value=Finding.trash.name).classes("mt-2")
        with ui.row().classes("justify-end w-full gap-2 mt-4"):
            c.button("Cancel", on_click=lambda: (dialog.close(), done())).classes("dw-btn-secondary").props(
                "unelevated no-caps"
            )

            def confirm() -> None:
                service.move_order(order_id, Stage.resolved, page.username, Finding[choice.value])
                ui.notify(f"{order_id} cleared. Inspection recorded.", type="positive")
                dialog.close()
                done()

            c.button("Mark as cleared", icon="task_alt", on_click=confirm).classes("dw-btn-primary").props(
                "unelevated no-caps"
            )
    dialog.open()


@ui.page("/work-orders")
async def work_orders_page() -> None:
    page = await shell("work", "Crews and work orders")
    if page is None:
        return
    drawer = DrainDrawer(page)
    element_to_order: dict[int, str] = {}
    column_stage: dict[int, Stage] = {}
    plan_state: dict = {"plan": None}
    sla_labels: dict[str, ui.label] = {}
    signature: dict[str, tuple] = {"board": ()}

    with ui.element("main").classes("dw-page w-full"):
        with ui.element("div").classes("dw-page-head"):
            with ui.column().classes("gap-1 max-w-[760px]"):
                ui.html('<h1 class="dw-h1">Crews and work orders</h1>', sanitize=False)
                ui.label(
                    "Drag a card to another column, or use Move to. Timers count down in simulated time and "
                    "turn red when an order is overdue."
                ).classes("dw-muted")
            c.button("Plan crew routes", icon="route", on_click=lambda: toggle_planner()).classes(
                "dw-btn-primary"
            ).props("unelevated no-caps")

        planner_box = ui.element("section").classes("dw-card w-full mb-4 overflow-hidden")
        planner_box.set_visibility(False)

        @ui.refreshable
        def crew_strip() -> None:
            rows = service.order_rows()
            busy = {r.order.crew_id: r for r in rows if r.order.stage in (Stage.en_route, Stage.active)}
            queued: dict[str, int] = {}
            for r in rows:
                if r.order.stage is Stage.pending and r.order.crew_id:
                    queued[r.order.crew_id] = queued.get(r.order.crew_id, 0) + 1
            with ui.element("div").classes("grid gap-3 w-full grid-cols-2 md:grid-cols-3 xl:grid-cols-5 mb-4"):
                for crew in service.crews():
                    job = busy.get(crew.id)
                    with ui.element("div").classes("dw-card px-4 py-3 flex flex-col gap-1"):
                        with ui.row().classes("items-center justify-between w-full no-wrap"):
                            ui.label(crew.name).classes("font-semibold text-[13.5px] truncate")
                            c.badge(
                                "Busy" if job else "Free",
                                "warning" if job else "ok",
                                "engineering" if job else "check_circle",
                            )
                        ui.label(crew.kind).classes("dw-xs dw-muted")
                        ui.label(
                            f"{service.STAGE_LABELS[job.order.stage]} at {job.drain.id}" if job else "Waiting at base"
                        ).classes("dw-xs")
                        if queued.get(crew.id):
                            ui.label(
                                f"{queued[crew.id]} more stop{'s' if queued[crew.id] != 1 else ''} queued"
                            ).classes("dw-xs dw-muted")

        crew_strip()

        @ui.refreshable
        def board() -> None:
            element_to_order.clear()
            column_stage.clear()
            sla_labels.clear()
            rows = visible_rows()
            signature["board"] = board_signature(rows)
            with ui.element("div").classes("grid gap-4 w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-4"):
                for stage in STAGE_ORDER:
                    items = [r for r in rows if r.order.stage is stage]
                    if stage is Stage.resolved:
                        items.sort(key=lambda r: r.order.closed_at or r.order.created, reverse=True)
                    with (
                        ui.element("section")
                        .classes("dw-column flex flex-col")
                        .props(f'aria-label="{service.STAGE_LABELS[stage]}, {len(items)} orders"')
                    ):
                        with ui.element("div").classes("dw-column-head"):
                            with ui.row().classes("items-center gap-2 no-wrap"):
                                ui.icon(STAGE_ICON[stage]).classes("dw-muted")
                                ui.label(service.STAGE_LABELS[stage]).classes("font-semibold text-[13.5px]")
                            ui.label(str(len(items))).classes("dw-count")
                        col = ui.column().classes("p-3 gap-3 w-full min-h-[360px] grow")
                        column_stage[col.id] = stage
                        with col:
                            for r in items:
                                card(r)
                        col.make_sortable(group="orders", on_end=dropped, animation=0.15)
                        if not items:
                            with col:
                                hint = {
                                    Stage.pending: "No orders waiting. Dispatch a crew from the queue, or use "
                                    "Plan crew routes.",
                                    Stage.en_route: "No crews travelling.",
                                    Stage.active: "No crews working on site.",
                                    Stage.resolved: "Cleared orders appear here.",
                                }[stage]
                                ui.label(hint).classes("dw-xs dw-muted text-center w-full py-6 dw-hint")

        def card(r: service.OrderRow) -> None:
            o = r.order
            band = r.score.band.value if r.score else "low"
            with ui.element("article").classes(f"dw-card-item edge-{band} is-draggable w-full") as el:
                element_to_order[el.id] = o.id
                with ui.row().classes("items-center justify-between w-full no-wrap"):
                    ui.label(o.id).classes("dw-mono font-semibold dw-small")
                    if r.score:
                        c.band_badge(band, r.score.score)
                with (
                    ui.element("button")
                    .classes("text-left w-full mt-1")
                    .props(f'type="button" aria-label="Open drain {r.drain.id}"')
                    .on("click", lambda d=r.drain.id: drawer.open(d))
                ):
                    ui.label(f"{r.drain.id} {r.drain.name}").classes("font-semibold text-[13.5px]")
                ui.label(o.task).classes("dw-xs dw-muted")
                with ui.column().classes("w-full mt-2 dw-xs gap-1"):
                    with ui.row().classes("items-center gap-1 no-wrap min-w-0 w-full"):
                        ui.icon("groups").classes("text-sm dw-muted")
                        crew_text = r.crew_name or "No crew yet"
                        if r.crew_name and o.stage is Stage.pending and o.route_order:
                            crew_text += f", stop {o.route_order}"
                        ui.label(crew_text).classes("truncate")
                    if o.stage is Stage.resolved:
                        ui.label(f"Cleared {o.closed_at:%H:%M}" if o.closed_at else "Cleared").classes("dw-muted")
                    else:
                        overdue = r.sla_min < 0
                        with (
                            ui.row()
                            .classes("items-center gap-1 no-wrap")
                            .style(f"color:var({'--critical-ink' if overdue else '--text'})")
                        ):
                            ui.icon("timer").classes("text-sm")
                            sla_labels[o.id] = ui.label(sla_text(r.sla_min)).classes("dw-tabular font-semibold")
                if r.eta_min is not None and o.stage is Stage.en_route:
                    ui.label(f"About {r.eta_min:.0f} min from base").classes("dw-xs dw-muted")
                if o.finding and o.stage is Stage.resolved:
                    ui.label(f"Found: {o.finding.value}").classes("dw-xs dw-muted")
                if o.stage is not Stage.resolved:
                    with ui.row().classes("w-full gap-2 mt-2 no-wrap"):
                        label = "Start this stop" if o.stage is Stage.pending and o.crew_id else NEXT_LABEL[o.stage]
                        c.button(label, on_click=lambda oid=o.id, st=o.stage: advance(oid, st)).classes(
                            "dw-btn-secondary grow"
                        ).props("unelevated dense no-caps")
                        with (
                            c.button(icon="more_horiz")
                            .classes("dw-btn-ghost")
                            .props('flat dense aria-label="Move to another column"')
                        ):
                            with ui.menu():
                                ui.label("Move to").classes("px-4 pt-2 dw-xs dw-muted")
                                for target in STAGE_ORDER:
                                    if target is not o.stage:
                                        ui.menu_item(
                                            service.STAGE_LABELS[target],
                                            on_click=lambda oid=o.id, t=target: move(oid, t),
                                        )

        board_box = ui.element("div").classes("w-full")

    def visible_rows() -> list[service.OrderRow]:
        rows = service.order_rows()
        if page.zone_id:
            rows = [r for r in rows if r.drain.zone_id == page.zone_id]
        return rows

    def board_signature(rows: list[service.OrderRow]) -> tuple:
        return tuple(
            (
                r.order.id,
                r.order.stage.value,
                r.order.crew_id,
                r.order.route_order,
                r.sla_min < 0,
                r.score.band.value if r.score else "",
            )
            for r in rows
        )

    def sla_text(minutes: float) -> str:
        return ("Overdue " if minutes < 0 else "SLA ") + c.minutes_text(abs(minutes))

    def advance(order_id: str, stage: Stage) -> None:
        nxt = STAGE_ORDER[STAGE_ORDER.index(stage) + 1]
        if stage is Stage.pending:
            o = service.order(order_id)
            if o and not o.crew_id:
                crew = service.nearest_free_crew(o.drain_id)
                if crew is None:
                    ui.notify("Every crew is busy. The order stays in Pending dispatch.", type="warning")
                    return
                service.assign_order(order_id, crew.id, page.username)
                ui.notify(f"{crew.name} is on the way.", type="positive")
                return
            if o and o.crew_id and o.crew_id not in {cr.id for cr in service.crews_available()}:
                ui.notify(
                    "That crew is still on another job. This stop stays queued until it finishes.", type="warning"
                )
                return
        move(order_id, nxt)

    def move(order_id: str, stage: Stage) -> None:
        if stage is Stage.resolved:
            finding_dialog(order_id, page, refresh)
            return
        service.move_order(order_id, stage, page.username)
        refresh()

    def dropped(e) -> None:
        order_id = element_to_order.get(e.item.id)
        stage = column_stage.get(e.target.id)
        if not order_id or stage is None:
            refresh()
            return
        o = service.order(order_id)
        if o is None or o.stage is stage:
            refresh()
            return
        move(order_id, stage)

    def refresh() -> None:
        board.refresh()
        crew_strip.refresh()

    with board_box:
        board()

    # ---------------------------------------------------------------- planner
    with planner_box:
        with ui.element("div").classes("grid grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)]"):
            with ui.column().classes("p-5 gap-4"):
                c.card_title("Plan crew routes", "Assigns jobs by priority, then by travel time from each crew.")
                n_label = ui.label().classes("dw-small font-semibold")
                n_crews = ui.slider(min=1, max=5, value=3).props('aria-label="Free crews to use"')
                n_label.bind_text_from(n_crews, "value", lambda v: f"Free crews to use: {v}")
                per_label = ui.label().classes("dw-small font-semibold")
                per_crew = ui.slider(min=1, max=6, value=3).props('aria-label="Inspections per crew"')
                per_label.bind_text_from(per_crew, "value", lambda v: f"Inspections per crew this shift: {v}")
                include = ui.checkbox("Add Critical and High drains that have no work order yet", value=True)
                with ui.row().classes("gap-2"):
                    c.button("Preview plan", icon="visibility", on_click=lambda: preview()).classes(
                        "dw-btn-secondary"
                    ).props("unelevated no-caps")
                    apply_btn = (
                        c.button("Apply plan", icon="check", on_click=lambda: apply())
                        .classes("dw-btn-primary")
                        .props("unelevated no-caps disable")
                    )

                @ui.refreshable
                def plan_list() -> None:
                    plan = plan_state["plan"]
                    if plan is None:
                        ui.label("Preview a plan to see each crew's stops here and on the map.").classes(
                            "dw-small dw-muted"
                        )
                        return
                    crews = {cr.id: cr.name for cr in service.crews()}
                    if not any(r.stops for r in plan.routes):
                        c.empty_state(
                            "Nothing to plan: no pending orders and no Critical or High drains without an "
                            "order, or no free crews.",
                            "route",
                        )
                        return
                    for route in plan.routes:
                        if not route.stops:
                            continue
                        with ui.column().classes("gap-1 w-full"):
                            ui.label(f"{crews[route.crew_id]}, about {route.total_min:.0f} min driving").classes(
                                "dw-small font-semibold"
                            )
                            for n, (job, leg) in enumerate(zip(route.stops, route.travel_min, strict=True), start=1):
                                new = " (new order)" if job.key == job.drain_id else ""
                                ui.label(
                                    f"{n}. {job.drain_id}, priority {job.priority:.0f}, {leg:.0f} min{new}"
                                ).classes("dw-xs")
                    if plan.leftover:
                        ui.label(
                            f"{len(plan.leftover)} job{'s' if len(plan.leftover) != 1 else ''} left for "
                            "later: crews are at capacity."
                        ).classes("dw-xs dw-muted")

                plan_list()

            with ui.element("div").classes("relative h-[460px] lg:h-auto min-h-[420px]"):
                planner_map = NetworkMap(
                    page.palette,
                    lambda: page.reduced_motion,
                    on_select=drawer.open,
                    state=MapState(layers=MapLayers(flow=False, reports=False, labels=0)),
                )

    def toggle_planner() -> None:
        planner_box.set_visibility(not planner_box.visible)
        if planner_box.visible:
            planner_map.restyle()

    def preview() -> None:
        plan = service.preview_plan(int(n_crews.value), int(per_crew.value), include.value)
        plan_state["plan"] = plan
        crews = {cr.id: cr for cr in service.crews()}
        routes = []
        for route in plan.routes:
            if not route.stops:
                continue
            crew = crews[route.crew_id]
            coords = [(crew.base_x, crew.base_y)] + [(j.x_m, j.y_m) for j in route.stops]
            routes.append((crew.name, coords, [j.drain_id for j in route.stops]))
        planner_map.state.routes = routes
        planner_map.refresh()
        plan_list.refresh()
        has_stops = any(r.stops for r in plan.routes)
        apply_btn.props(remove="disable") if has_stops else apply_btn.props(add="disable")

    def apply() -> None:
        plan = plan_state["plan"]
        if plan is None:
            return
        count = service.apply_plan(plan, page.username)
        ui.notify(f"Plan applied: {count} stops assigned. First stops are on the way.", type="positive")
        plan_state["plan"] = None
        planner_map.state.routes = []
        planner_map.refresh()
        plan_list.refresh()
        apply_btn.props(add="disable")
        refresh()

    def live() -> None:
        rows = visible_rows()
        if board_signature(rows) != signature["board"]:
            refresh()
        else:
            for r in rows:
                label = sla_labels.get(r.order.id)
                if label is not None:
                    label.set_text(sla_text(r.sla_min))
            crew_strip.refresh()
        if planner_box.visible:
            planner_map.refresh()

    page.on_live(live)
    page.on_theme(planner_map.restyle)
