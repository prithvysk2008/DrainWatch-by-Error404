"""Incidents and complaints: reports from citizens, patrols, crews and the control room during this storm."""

from __future__ import annotations

from nicegui import app, ui

from drainwatch import service
from drainwatch.models import ReportStatus, ReportType, Severity
from ui import components as c
from ui.drawer import DrainDrawer
from ui.layout import log_incident_dialog, shell


def reporter_text(r) -> str:
    """'Patrol unit 5' rather than 'Patrol: Patrol unit 5'."""
    if r.reporter.lower().startswith(r.source.value.lower().split()[0]):
        return r.reporter
    return f"{r.source.value}: {r.reporter}"


@ui.page("/incidents")
async def incidents_page() -> None:
    page = await shell("incidents", "Incidents and complaints")
    if page is None:
        return
    drawer = DrainDrawer(page)
    filters = app.storage.user.setdefault("incident_filters", {"status": "", "type": "", "severity": ""})

    with ui.element("main").classes("dw-page w-full"):
        with ui.element("div").classes("dw-page-head"):
            with ui.column().classes("gap-1 max-w-[760px]"):
                ui.html('<h1 class="dw-h1">Incidents and complaints</h1>', sanitize=False)
                ui.label(
                    "Citizen helpline calls, patrol observations, crew reports and control room entries. "
                    "Each report raises the priority of drains within 75 m until a crew clears it."
                ).classes("dw-muted")
            c.button("Log field incident", icon="add", on_click=lambda: log_incident_dialog(page)).classes(
                "dw-btn-primary"
            ).props("unelevated no-caps")

        with ui.element("div").classes("dw-card dw-card-pad w-full grid gap-3 grid-cols-1 md:grid-cols-4 items-end"):
            status = ui.select(
                {"": "All statuses"} | {s.value: c.REPORT_STATUS_TEXT[s.value] for s in ReportStatus},
                value=filters["status"],
                label="Status",
                on_change=lambda e: set_filter("status", e.value),
            ).props("outlined dense options-dense")
            kind = ui.select(
                {"": "All issue types"} | {t.value: t.value for t in ReportType},
                value=filters["type"],
                label="Issue category",
                on_change=lambda e: set_filter("type", e.value),
            ).props("outlined dense options-dense")
            severity = ui.select(
                {"": "All severities"} | {s.value: c.SEVERITY_TEXT[s.value] for s in Severity},
                value=filters["severity"],
                label="Severity",
                on_change=lambda e: set_filter("severity", e.value),
            ).props("outlined dense options-dense")
            c.button("Reset filters", icon="filter_alt_off", on_click=lambda: reset()).classes(
                "dw-btn-secondary"
            ).props("unelevated no-caps")

        @ui.refreshable
        def grid() -> None:
            rows = service.incidents(filters["status"] or None, filters["type"] or None, filters["severity"] or None)
            if page.zone_id:
                rows = [r for r in rows if r.drain.zone_id == page.zone_id]
            ui.label(f"{len(rows)} report{'s' if len(rows) != 1 else ''}").classes("dw-small dw-muted mt-4 mb-2")
            if not rows:
                any_filter = any(filters.values())
                c.empty_state(
                    "No reports match these filters. Reset filters to see every report."
                    if any_filter
                    else "No reports during this storm yet. They arrive as the storm runs, "
                    "or log one with Log field incident.",
                    "campaign",
                )
                return
            now = service.now()
            with ui.element("div").classes("grid gap-4 w-full grid-cols-1 md:grid-cols-2 2xl:grid-cols-3"):
                for row in rows:
                    r = row.report
                    with ui.element("article").classes("dw-card dw-card-pad flex flex-col gap-2"):
                        with ui.row().classes("items-center justify-between w-full"):
                            with ui.row().classes("items-center gap-2"):
                                c.severity_badge(r.severity.value)
                                c.badge(c.REPORT_STATUS_TEXT[r.status.value], c.REPORT_STATUS_TONE[r.status.value])
                            ui.label(c.ago(r.ts, now)).classes("dw-xs dw-muted")
                        with ui.column().classes("gap-0"):
                            ui.label(row.drain.name).classes("font-semibold text-[15px]")
                            ui.label(f"{r.id}, drain {r.drain_id}, {r.type.value}").classes("dw-small dw-muted")
                        ui.label(r.description).classes("dw-small")
                        if r.duplicate_of:
                            ui.label(f"Possible duplicate of {r.duplicate_of}: same drain within the hour.").classes(
                                "dw-xs dw-muted"
                            )
                        if r.photo_path:
                            ui.image(r.photo_path).classes("w-full max-h-[180px] rounded").props(
                                f'fit=cover alt="Photo attached to report {r.id}"'
                            )
                        ui.separator().classes("my-1")
                        with ui.row().classes("items-center justify-between w-full"):
                            ui.label(reporter_text(r) + (f". Crew: {row.crew_name}" if row.crew_name else "")).classes(
                                "dw-xs dw-muted"
                            )
                            with ui.row().classes("gap-2"):
                                c.button("View drain", on_click=lambda d=r.drain_id: drawer.open(d)).classes(
                                    "dw-btn-ghost"
                                ).props("flat dense no-caps")
                                if r.status is ReportStatus.new:
                                    c.button(
                                        "Dispatch crew",
                                        icon="local_shipping",
                                        on_click=lambda d=r.drain_id: dispatch(d),
                                    ).classes("dw-btn-primary").props("unelevated dense no-caps")

        grid()

    def set_filter(key: str, value: str | None) -> None:
        filters[key] = value or ""
        app.storage.user["incident_filters"] = filters
        grid.refresh()

    def reset() -> None:
        for key, el in (("status", status), ("type", kind), ("severity", severity)):
            filters[key] = ""
            el.set_value("")
        app.storage.user["incident_filters"] = filters
        grid.refresh()

    def dispatch(drain_id: str) -> None:
        order, crew = service.dispatch(drain_id, page.username)
        if crew:
            ui.notify(f"{crew.name} sent to {drain_id}. Work order {order.id}.", type="positive")
        else:
            ui.notify(
                f"Work order {order.id} created. Every crew is busy, so it waits in Pending dispatch.", type="warning"
            )

    page.on_live(grid.refresh)
