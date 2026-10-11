"""Field crew screens. Phone-first: one column, large touch targets, bottom navigation."""

from __future__ import annotations

import html
import json
import math

from nicegui import app, ui

from drainwatch import service
from drainwatch.models import Finding, ReportSource, ReportType, Severity, Stage
from ui import components as c
from ui.layout import Page, detect_client, head
from ui.map_view import MapLayers, MapState, NetworkMap

PREVIEW_CREW = "C2"
STAGE_TONE = {Stage.pending: "neutral", Stage.en_route: "info", Stage.active: "warning", Stage.resolved: "ok"}
STAGE_SHORT = {
    Stage.pending: "Queued",
    Stage.en_route: "On the way",
    Stage.active: "Working on site",
    Stage.resolved: "Cleared",
}


async def crew_shell(active: str, title: str) -> tuple[Page, str] | None:
    user = app.storage.user.get("user")
    if not user:
        ui.navigate.to("/login")
        return None
    head()
    pref = app.storage.user.get("theme", "system")
    dark, reduced = await detect_client(pref)
    dark_mode = ui.dark_mode(dark)
    page = Page(user["username"], user["display_name"], dark, reduced)
    crew_id = user.get("crew_id") or PREVIEW_CREW
    crew = next(cr for cr in service.crews() if cr.id == crew_id)
    ui.page_title(f"{title} | Drain Watch crew")

    def toggle_theme() -> None:
        page.dark = not page.dark
        app.storage.user["theme"] = "dark" if page.dark else "light"
        dark_mode.value = page.dark
        page.fire_theme()

    with ui.header().classes("dw-crew-top items-center no-wrap gap-2 px-3"):
        with ui.element("div").classes("dw-brand-mark shrink-0"):
            ui.icon("water_drop").classes("text-xl")
        with ui.column().classes("gap-0 min-w-0"):
            ui.label(crew.name).classes("font-semibold text-[15px] truncate").style("color:var(--topbar-text)")

            @ui.refreshable
            def clock() -> None:
                st = service.state()
                ui.label(f"{st.sim_time:%H:%M} simulated. {st.scenario}").classes("dw-xs truncate").style(
                    "color:var(--topbar-muted)"
                )

            clock()
        ui.space()
        c.button(icon="contrast", on_click=toggle_theme).classes("dw-icon-btn").props('flat aria-label="Switch theme"')
        with c.button(icon="account_circle").classes("dw-icon-btn").props('flat aria-label="Account menu"'):
            with ui.menu().classes("min-w-[220px]"):
                with ui.column().classes("px-4 py-3 gap-0"):
                    ui.label(page.display_name).classes("font-semibold")
                    ui.label(
                        "Field crew, demo account" if user["role"] == "crew" else "Operator previewing the crew view"
                    ).classes("dw-small dw-muted")
                ui.separator()
                if user["role"] == "operator":
                    ui.menu_item("Back to the control room", on_click=lambda: ui.navigate.to("/"))
                ui.menu_item("About and method", on_click=lambda: ui.navigate.to("/about"))
                ui.menu_item(
                    "Sign out", on_click=lambda: (app.storage.user.pop("user", None), ui.navigate.to("/login"))
                )

    with ui.footer().classes("dw-crew-nav p-0").props('role="navigation" aria-label="Crew navigation"'):
        with ui.row().classes("w-full no-wrap gap-0 max-w-[560px] mx-auto"):
            for key, href, icon, label in (
                ("tasks", "/crew", "assignment", "My tasks"),
                ("report", "/crew/report", "add_alert", "Report a blockage"),
            ):
                with (
                    ui.link(target=href)
                    .classes("is-active" if key == active else "")
                    .props('aria-current="page"' if key == active else "")
                ):
                    ui.icon(icon).classes("text-2xl")
                    ui.label(label)

    def poll() -> None:
        v = service.version()
        if v != page.version:
            page.version = v
            clock.refresh()
            page.fire_live()

    page.version = service.version()
    ui.timer(1.0, poll)
    return page, crew_id


def crew_orders(crew_id: str) -> list[service.OrderRow]:
    rows = service.order_rows(crew_id)
    stage_rank = {Stage.active: 0, Stage.en_route: 1, Stage.pending: 2, Stage.resolved: 3}
    return sorted(
        rows, key=lambda r: (stage_rank[r.order.stage], r.order.route_order or 99, -(r.score.score if r.score else 0))
    )


def distance_km(crew_id: str, drain: service.DrainInfo) -> float:
    crew = next(cr for cr in service.crews() if cr.id == crew_id)
    return math.hypot(crew.base_x - drain.x, crew.base_y - drain.y) / 1000


@ui.page("/crew")
async def crew_tasks_page() -> None:
    shell = await crew_shell("tasks", "My tasks")
    if shell is None:
        return
    page, crew_id = shell

    with ui.element("main").classes("dw-crew-shell"):
        ui.html('<h1 class="dw-h1">My tasks</h1>', sanitize=False)
        ui.label("Sorted by stage, route order and priority. Tap a task to open it.").classes("dw-small dw-muted mt-1")

        @ui.refreshable
        def tasks() -> None:
            rows = crew_orders(crew_id)
            open_rows = [r for r in rows if r.order.stage is not Stage.resolved]
            done = [r for r in rows if r.order.stage is Stage.resolved]
            with ui.column().classes("w-full gap-3 mt-4"):
                if not open_rows:
                    c.empty_state(
                        "No tasks assigned to your crew right now. New work appears here when the control "
                        "room dispatches you.",
                        "assignment_turned_in",
                    )
                for r in open_rows:
                    o, sc = r.order, r.score
                    band = sc.band.value if sc else "low"
                    with (
                        ui.link(target=f"/crew/task/{o.id}")
                        .classes(f"dw-card-item edge-{band} w-full no-underline block")
                        .style("color:inherit")
                    ):
                        with ui.row().classes("items-center justify-between w-full no-wrap"):
                            c.badge(STAGE_SHORT[o.stage], STAGE_TONE[o.stage])
                            if sc:
                                c.band_badge(band, sc.score, solid=True)
                        ui.label(f"{r.drain.id} {r.drain.name}").classes("font-semibold text-[16px] mt-2")
                        ui.label(o.task).classes("dw-small dw-muted")
                        if sc:
                            ui.label(sc.label.value).classes("dw-small mt-1")
                        with ui.row().classes("items-center justify-between w-full mt-3 dw-small no-wrap"):
                            with ui.row().classes("items-center gap-1 no-wrap"):
                                ui.icon("near_me").classes("text-base dw-muted")
                                ui.label(f"{distance_km(crew_id, r.drain):.1f} km from base")
                            overdue = r.sla_min < 0
                            with (
                                ui.row()
                                .classes("items-center gap-1 no-wrap")
                                .style(f"color:var({'--critical-ink' if overdue else '--text'})")
                            ):
                                ui.icon("timer").classes("text-base")
                                ui.label(
                                    ("Overdue " if overdue else "Due in ") + c.minutes_text(abs(r.sla_min))
                                ).classes("font-semibold dw-tabular")
                if done:
                    ui.label(f"Cleared this shift: {len(done)}").classes("dw-section-title mt-4")
                    for r in done[:10]:
                        with (
                            ui.row()
                            .classes("w-full items-center justify-between dw-small py-2")
                            .style("border-bottom:1px solid var(--border)")
                        ):
                            ui.label(f"{r.drain.id} {r.drain.name}").classes("truncate")
                            ui.label(f"{r.order.closed_at:%H:%M}" if r.order.closed_at else "").classes("dw-muted")

        tasks()

    page.on_live(tasks.refresh)


@ui.page("/crew/task/{order_id}")
async def crew_task_page(order_id: str) -> None:
    shell = await crew_shell("tasks", "Task")
    if shell is None:
        return
    page, crew_id = shell

    with ui.element("main").classes("dw-crew-shell"):
        ui.link("Back to my tasks", "/crew").classes("dw-link dw-small")

        @ui.refreshable
        def body() -> None:
            o = service.order(order_id)
            if o is None:
                c.empty_state("This task no longer exists. Go back to My tasks.", "error_outline")
                return
            detail = service.drain_detail(o.drain_id)
            assert detail is not None
            info, sc = detail.info, detail.score
            checklist: dict[str, bool] = json.loads(o.checklist_json or "{}") or dict.fromkeys(service.CHECKLIST, False)
            with ui.column().classes("w-full gap-4 mt-3"):
                with ui.column().classes("gap-1"):
                    with ui.row().classes("items-center gap-2"):
                        ui.label(o.id).classes("dw-mono dw-small dw-muted")
                        c.badge(STAGE_SHORT[o.stage], STAGE_TONE[o.stage])
                        if sc:
                            c.band_badge(sc.band.value, sc.score, solid=True)
                    ui.html(f'<h1 class="dw-h1">{info.id} {html.escape(info.name)}</h1>', sanitize=False)
                    ui.label(f"{info.zone_name}, {info.ward}. {o.task}.").classes("dw-small dw-muted")

                with ui.element("section").classes("dw-card overflow-hidden w-full h-[240px] relative"):
                    task_map = NetworkMap(
                        page.palette,
                        lambda: page.reduced_motion,
                        state=MapState(selected=info.id, layers=MapLayers(flow=False, reports=True, labels=0)),
                    )
                    holder["map"] = task_map

                with ui.element("section").classes("dw-card dw-card-pad w-full"):
                    ui.label("Why it was flagged").classes("dw-card-title")
                    if sc:
                        ui.label(sc.label.value).classes("font-semibold mt-1")
                        ui.label(sc.explanation).classes("dw-body mt-1")
                        ui.label(f"Confidence {sc.confidence * 100:.0f}%. {sc.confidence_reason}").classes(
                            "dw-small dw-muted mt-2"
                        )

                with ui.element("section").classes("dw-card dw-card-pad w-full"):
                    ui.label("Checklist").classes("dw-card-title")
                    for item in service.CHECKLIST:
                        with ui.element("div").classes("dw-check"):
                            ui.checkbox(
                                item, value=checklist.get(item, False), on_change=lambda e, it=item: tick(it, e.value)
                            ).classes("text-[15px]")

                with ui.element("section").classes("dw-card dw-card-pad w-full"):
                    ui.label("Photos").classes("dw-card-title")
                    ui.label("JPG, PNG or WebP, up to 8 MB. Do not photograph people or number plates.").classes(
                        "dw-xs dw-muted"
                    )
                    with ui.element("div").classes("grid grid-cols-2 gap-3 mt-3"):
                        for which, path in (("before", o.photo_before), ("after", o.photo_after)):
                            with ui.column().classes("gap-2"):
                                ui.label(f"Photo {which}").classes("dw-small font-semibold")
                                if path:
                                    ui.image(path).classes("w-full h-[120px] rounded").props(
                                        f'fit=cover alt="Photo {which} the work at {info.id}"'
                                    )
                                ui.upload(
                                    label="Replace" if path else "Add photo",
                                    auto_upload=True,
                                    max_file_size=service.MAX_PHOTO_BYTES,
                                    on_upload=lambda e, w=which: upload(e, w),
                                    on_rejected=lambda: ui.notify(
                                        "That file is too large. Use a photo up to 8 MB.", type="warning"
                                    ),
                                ).props('accept="image/jpeg,image/png,image/webp" flat bordered').classes(
                                    "w-full dw-upload"
                                )

                with ui.element("section").classes("dw-card dw-card-pad w-full"):
                    ui.label("Notes and finding").classes("dw-card-title")
                    finding = (
                        ui.select(
                            {f.name: f.value for f in Finding},
                            value=o.finding.name if o.finding else None,
                            label="What did you find?",
                            on_change=lambda e: (
                                service.update_order(order_id, finding=Finding[e.value]) if e.value else None
                            ),
                        )
                        .props("outlined")
                        .classes("w-full mt-2")
                    )
                    notes = ui.textarea("Notes", value=o.notes).props("outlined autogrow").classes("w-full mt-2")
                    c.button(
                        "Save notes",
                        icon="save",
                        on_click=lambda: (
                            service.update_order(order_id, notes=notes.value or ""),
                            ui.notify("Notes saved.", type="positive"),
                        ),
                    ).classes("dw-btn-secondary dw-touch w-full mt-2").props("unelevated no-caps")

                with ui.column().classes("w-full gap-2"):
                    if o.stage is Stage.pending:
                        c.button("On my way", icon="local_shipping", on_click=lambda: start(Stage.en_route)).classes(
                            "dw-btn-primary dw-touch w-full"
                        ).props("unelevated no-caps")
                    elif o.stage is Stage.en_route:
                        c.button(
                            "Start work on site", icon="construction", on_click=lambda: start(Stage.active)
                        ).classes("dw-btn-primary dw-touch w-full").props("unelevated no-caps")
                    elif o.stage is Stage.active:
                        c.button("Mark as cleared", icon="task_alt", on_click=lambda: clear(finding.value)).classes(
                            "dw-btn-primary dw-touch w-full"
                        ).props("unelevated no-caps")
                        ui.label("Clearing records an inspection and lowers this drain's priority.").classes(
                            "dw-xs dw-muted text-center w-full"
                        )
                    else:
                        c.badge(f"Cleared at {o.closed_at:%H:%M}" if o.closed_at else "Cleared", "ok", "task_alt")

        holder: dict = {}
        body()

    def tick(item: str, value: bool) -> None:
        o = service.order(order_id)
        if o is None:
            return
        state = json.loads(o.checklist_json or "{}") or dict.fromkeys(service.CHECKLIST, False)
        state[item] = value
        service.update_order(order_id, checklist=state)

    async def upload(e, which: str) -> None:
        try:
            path = service.save_photo(f"{order_id}-{which}", e.file.name, await e.file.read())
        except ValueError as exc:
            ui.notify(str(exc), type="warning")
            return
        if which == "before":
            service.update_order(order_id, photo_before=path)
        else:
            service.update_order(order_id, photo_after=path)
        tick(f"Photo {which}", True)
        ui.notify(f"Photo {which} saved.", type="positive")
        body.refresh()

    def start(stage: Stage) -> None:
        o = service.order(order_id)
        if o is None:
            return
        if not o.crew_id:
            service.assign_order(order_id, crew_id, page.username)
        service.move_order(order_id, stage, page.username)
        body.refresh()

    def clear(finding_name: str | None) -> None:
        if not finding_name:
            ui.notify("Choose what you found before marking the task as cleared.", type="warning")
            return
        service.move_order(order_id, Stage.resolved, page.username, Finding[finding_name])
        ui.notify("Task cleared. Inspection recorded and priority lowered.", type="positive")
        body.refresh()

    def live() -> None:
        task_map = holder.get("map")
        if task_map is not None:
            task_map.refresh()

    page.on_live(live)
    page.on_theme(lambda: holder["map"].restyle() if "map" in holder else None)


@ui.page("/crew/report")
async def crew_report_page() -> None:
    shell = await crew_shell("report", "Report a blockage")
    if shell is None:
        return
    page, _ = shell
    photo: dict[str, str | None] = {"path": None}

    with ui.element("main").classes("dw-crew-shell"):
        ui.html('<h1 class="dw-h1">Report a blockage</h1>', sanitize=False)
        ui.label("Your report reaches the control room straight away and raises the drain's priority.").classes(
            "dw-small dw-muted mt-1"
        )
        with ui.column().classes("w-full gap-4 mt-4"):
            options = {
                d.id: f"{d.id}  {d.name}" for d in sorted((r.info for r in service.drain_rows()), key=lambda d: d.id)
            }
            drain = ui.select(options, label="Drain", with_input=True).props("outlined").classes("w-full")
            ui.label("Issue").classes("dw-section-title")
            kind = ui.radio({t.name: t.value for t in ReportType}, value=ReportType.trash.name).classes("text-[15px]")
            ui.label("Severity").classes("dw-section-title")
            severity = ui.radio({s.name: c.SEVERITY_TEXT[s.value] for s in Severity}, value=Severity.high.name).classes(
                "text-[15px]"
            )
            notes = (
                ui.textarea(
                    "What you can see",
                    placeholder="For example: grate covered with leaves, water spreading across the lane",
                )
                .props("outlined autogrow")
                .classes("w-full")
            )

            async def got_photo(e) -> None:
                try:
                    photo["path"] = service.save_photo("report", e.file.name, await e.file.read())
                    ui.notify("Photo attached.", type="positive")
                except ValueError as exc:
                    ui.notify(str(exc), type="warning")

            ui.upload(
                label="Add a photo (optional)",
                auto_upload=True,
                max_file_size=service.MAX_PHOTO_BYTES,
                on_upload=got_photo,
            ).props('accept="image/jpeg,image/png,image/webp" flat bordered').classes("w-full dw-upload")
            error = ui.label().classes("dw-small").style("color:var(--critical-ink)").props('role="alert"')

            def submit() -> None:
                if not drain.value:
                    error.set_text("Choose the drain you are reporting.")
                    return
                before = service.score_for(drain.value)
                report = service.log_report(
                    drain.value,
                    ReportType[kind.value],
                    Severity[severity.value],
                    ReportSource.crew,
                    page.display_name,
                    notes.value or "Reported by a field crew.",
                    page.username,
                    photo_path=photo["path"],
                )
                after = service.score_for(drain.value)
                change = f" Priority {before.score:.0f} to {after.score:.0f}." if before and after else ""
                ui.notify(f"Report {report.id} sent for {drain.value}.{change}", type="positive")
                drain.set_value(None)
                notes.set_value("")
                photo["path"] = None
                error.set_text("")

            c.button("Send report", icon="send", on_click=submit).classes("dw-btn-primary dw-touch w-full").props(
                "unelevated no-caps"
            )
