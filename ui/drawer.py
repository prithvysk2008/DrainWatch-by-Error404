"""Drain detail drawer. Opens from the map, the queue, notifications and search on every operator page."""

from __future__ import annotations

import html

from nicegui import ui

from drainwatch import service
from drainwatch.models import Stage
from ui import charts
from ui import components as c
from ui.layout import Page, log_incident_dialog

SITE_TEXT = {
    "underpass": "Underpass",
    "hospital": "Hospital",
    "school": "School",
    "market": "Market",
    "depot": "Bus depot",
}


class DrainDrawer:
    def __init__(self, page: Page, on_change=None) -> None:
        self.page = page
        self.drain_id: str | None = None
        self.tab = "Details"
        self._on_change = on_change
        with (
            ui.right_drawer(value=False, fixed=True)
            .classes("dw-drawer p-0")
            .props("width=460 overlay elevated behavior=mobile") as self.drawer
        ):
            self.body = ui.column().classes("w-full gap-0 no-wrap")
        page.open_drain = self.open
        page.on_live(self._live)
        page.on_theme(self._render)

    def open(self, drain_id: str) -> None:
        self.drain_id = drain_id
        self._render()
        self.drawer.show()
        if self._on_change:
            self._on_change(drain_id)

    def close(self) -> None:
        self.drawer.hide()
        self.drain_id = None
        if self._on_change:
            self._on_change(None)

    def _live(self) -> None:
        if self.drain_id and self.drawer.value:
            self._render()

    def _render(self) -> None:
        self.body.clear()
        if not self.drain_id:
            return
        d = service.drain_detail(self.drain_id)
        if d is None:
            return
        info, sc = d.info, d.score
        p = self.page.palette()
        open_order = next((o for o in d.orders if o.stage is not Stage.resolved), None)
        crew_names = {cr.id: cr.name for cr in service.crews()}
        with self.body:
            # header
            with ui.column().classes("w-full gap-2 px-5 pt-4 pb-3"):
                with ui.row().classes("w-full items-start justify-between no-wrap"):
                    with ui.column().classes("gap-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(info.id).classes("dw-mono text-[20px] font-bold")
                            if sc:
                                c.band_badge(sc.band.value, sc.score, solid=True)
                        ui.label(info.name).classes("font-semibold text-[15px] leading-tight")
                        ui.label(
                            f"{info.zone_name}, {info.ward}" + (f". Serves {info.site_name}" if info.site_name else "")
                        ).classes("dw-small dw-muted")
                    c.button(icon="close", on_click=self.close).props(
                        'flat round dense aria-label="Close drain details"'
                    )
                with ui.row().classes("items-center gap-2 wrap"):
                    if sc:
                        c.fill_badge(sc.fill_status.value, sc.fill_pct if sc.sensor_ok else None)
                        c.label_badge(sc.label.value)
                    owner = crew_names.get(open_order.crew_id) if open_order and open_order.crew_id else None
                    c.badge(
                        f"Owner: {owner}" if owner else ("Order open, no crew yet" if open_order else "Unassigned"),
                        "info" if owner else "neutral",
                        "engineering",
                    )
            with (
                ui.tabs(value=self.tab, on_change=lambda e: setattr(self, "tab", e.value))
                .classes("dw-tabs w-full px-3")
                .props("dense align=left no-caps") as tabs
            ):
                for name in ("Details", "Readings", "Reports", "History"):
                    ui.tab(name)
            ui.separator()
            with ui.tab_panels(tabs, value=self.tab).classes("w-full bg-transparent").props("animated=false"):
                with ui.tab_panel("Details").classes("px-5 py-4"):
                    self._details(d, p, open_order)
                with ui.tab_panel("Readings").classes("px-5 py-4"):
                    self._readings(d, p)
                with ui.tab_panel("Reports").classes("px-5 py-4"):
                    self._reports(d)
                with ui.tab_panel("History").classes("px-5 py-4"):
                    self._history(d, crew_names)

    # ------------------------------------------------------------ tabs

    def _details(self, d: service.DrainDetail, p, open_order) -> None:
        info, sc = d.info, d.score
        if sc is None:
            return
        with ui.column().classes("w-full gap-4"):
            with ui.element("div").classes("dw-inset p-4 w-full"):
                with ui.row().classes("items-end justify-between w-full"):
                    with ui.column().classes("gap-0"):
                        ui.label("Priority score").classes("dw-small dw-muted")
                        with ui.row().classes("items-baseline gap-1"):
                            ui.label(f"{sc.score:.0f}").classes("dw-kpi-value")
                            ui.label("of 100").classes("dw-kpi-unit")
                    with ui.column().classes("gap-0 items-end"):
                        ui.label("Rank").classes("dw-small dw-muted")
                        ui.label(f"{d.rank} of {service.kpis()['monitored']}").classes("font-semibold dw-mono")
                ui.label(sc.explanation).classes("dw-body mt-3")
            with ui.column().classes("w-full gap-1"):
                with ui.row().classes("justify-between w-full"):
                    ui.label("Confidence").classes("dw-section-title")
                    ui.label(f"{sc.confidence * 100:.0f}%").classes("dw-mono font-semibold")
                c.meter(sc.confidence * 100, "--info" if sc.confidence >= 0.6 else "--unknown", "Confidence")
                ui.label(sc.confidence_reason).classes("dw-small dw-muted")
            with ui.column().classes("w-full gap-1"):
                ui.label("What contributed to the score").classes("dw-section-title")
                ui.label("Points out of 100. Weights: water level 40, rainfall 30, history 20, reports 10.").classes(
                    "dw-xs dw-muted"
                )
                ui.echart(charts.contributions(sc.contributions, p)).classes("w-full h-[180px]")
            level = (
                f"{sc.level_cm:.0f} cm of {info.max_depth_cm:.0f} cm ({sc.fill_pct:.0f}%)"
                if sc.level_cm is not None and sc.sensor_ok
                else "No working sensor"
            )
            expected = f"{sc.expected_cm:.0f} cm" if sc.expected_cm is not None and info.has_sensor else "Not known"
            sluggish = d.velocity_ms < 0.4
            velocity = f"{d.velocity_ms:.2f} m/s" + (", sluggish: possible silt or debris" if sluggish else "")
            rows = [
                ("Water level", level),
                ("Expected for this rain", expected),
                ("Flow velocity (simulated)", velocity if info.has_sensor else "Not measured"),
                ("Silt estimate (simulated)", f"{info.silt_pct:.0f}% of depth"),
                ("Last inspected", f"{info.last_inspected:%d %b %Y}" if info.last_inspected else "No record"),
                ("Blockages in the past year", str(info.past_blockages)),
                ("Silt-prone", "Yes" if info.silt_prone else "No"),
                ("Nearby drains also high", ", ".join(d.neighbours_high) if d.neighbours_high else "None"),
            ]
            if info.critical_site:
                rows.append(("Critical site", f"{SITE_TEXT.get(info.critical_site, '')}, {info.site_name}"))
            if d.sensor:
                rows.append(("Sensor", f"{d.sensor.serial}, battery {d.sensor.battery_pct}%"))
            items = "".join(f"<dt>{html.escape(k)}</dt><dd>{html.escape(v)}</dd>" for k, v in rows)
            ui.html(f'<dl class="dw-kv">{items}</dl>', sanitize=False).classes("w-full")
            with ui.column().classes("w-full gap-2 pt-1"):
                if open_order:
                    ui.label(f"Work order {open_order.id} is open: {open_order.task}.").classes("dw-small dw-muted")
                c.button(
                    "Dispatch desilting crew" if not open_order or not open_order.crew_id else "Crew already sent",
                    icon="local_shipping",
                    on_click=lambda: self._dispatch(info.id),
                ).classes("dw-btn-primary w-full").props(
                    "unelevated no-caps" + (" disable" if open_order and open_order.crew_id else "")
                )
                with ui.row().classes("w-full gap-2 no-wrap"):
                    c.button(
                        "Log report", icon="campaign", on_click=lambda: log_incident_dialog(self.page, info.id)
                    ).classes("dw-btn-secondary grow").props("unelevated no-caps")
                    c.button("Mark false alarm", icon="flag", on_click=lambda: self._false_alarm(info.id)).classes(
                        "dw-btn-danger grow"
                    ).props("unelevated no-caps")
                ui.label(
                    "Mark false alarm closes the open reports on this drain and resets its sensor if it has "
                    "stopped reporting properly."
                ).classes("dw-xs dw-muted")

    def _readings(self, d: service.DrainDetail, p) -> None:
        info = d.info
        th = service.thresholds()
        if not info.has_sensor:
            c.empty_state(
                "This drain has no water-level sensor. Its priority comes from reports, history and the "
                "drains around it.",
                "sensors_off",
            )
            return
        ui.label(
            "Observed level against the level expected for the rain so far. The shaded band is the normal "
            "range. Rain in this zone is shown below on its own scale."
        ).classes("dw-small dw-muted")
        ui.echart(
            charts.readings(
                d.times,
                d.observed,
                d.expected,
                d.spread,
                d.rain_mm_10min,
                info.max_depth_cm,
                th.warning,
                th.critical,
                p,
            )
        ).classes("w-full h-[320px] mt-2")
        with ui.row().classes("gap-4 dw-xs dw-muted"):
            for color, text in (
                (p.accent, "Observed"),
                (p.expected, "Expected for this rain"),
                (p.info, "Rain, mm per 10 min"),
            ):
                with ui.row().classes("items-center gap-1 no-wrap"):
                    ui.element("span").classes("dw-legend-dot").style(f"background:{color}")
                    ui.label(text)
        with ui.expansion("Show the last 12 readings as a table").classes("w-full mt-3 dw-small"):
            rows = list(zip(d.times, d.observed, d.expected, strict=True))[-12:]
            ui.table(
                rows=[{"t": t, "o": "No data" if o is None else f"{o:.1f}", "e": f"{e:.1f}"} for t, o, e in rows],
                columns=[
                    {"name": "t", "label": "Time", "field": "t", "align": "left"},
                    {"name": "o", "label": "Observed, cm", "field": "o"},
                    {"name": "e", "label": "Expected, cm", "field": "e"},
                ],
                row_key="t",
            ).classes("dw-table w-full").props("flat dense hide-bottom")

    def _reports(self, d: service.DrainDetail) -> None:
        now = service.now()
        if not d.reports:
            c.empty_state(
                "No reports within 75 m during this storm. Use Log report if a crew or caller "
                "describes a problem here.",
                "campaign",
            )
            return
        with ui.column().classes("w-full gap-2"):
            for r in d.reports:
                with ui.element("div").classes("dw-inset p-3 w-full"):
                    with ui.row().classes("items-center justify-between w-full"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(r.id).classes("dw-mono font-semibold")
                            c.severity_badge(r.severity.value)
                            c.badge(c.REPORT_STATUS_TEXT[r.status.value], c.REPORT_STATUS_TONE[r.status.value])
                        ui.label(c.ago(r.ts, now)).classes("dw-xs dw-muted")
                    ui.label(f"{r.type.value}. {r.source.value}, {r.reporter}.").classes("dw-small mt-1")
                    ui.label(r.description).classes("dw-small dw-muted")
                    if r.drain_id != d.info.id:
                        ui.label(f"Logged against {r.drain_id}, within 75 m.").classes("dw-xs dw-muted")
                    if r.duplicate_of:
                        ui.label(f"Possible duplicate of {r.duplicate_of}. Counted once in the score.").classes(
                            "dw-xs dw-muted"
                        )
                    if r.photo_path:
                        ui.image(r.photo_path).classes("w-full max-w-[240px] rounded mt-2").props(
                            f'alt="Photo attached to report {r.id}"'
                        )

    def _history(self, d: service.DrainDetail, crew_names: dict[str, str]) -> None:
        events: list[tuple] = []
        for a in d.audit:
            events.append((a.ts, a.action, f"{a.actor}" + (f". {a.detail}" if a.detail else "")))
        for o in d.orders:
            crew = crew_names.get(o.crew_id, "no crew") if o.crew_id else "no crew"
            events.append(
                (o.created, f"Work order {o.id}", f"{o.task}. {crew}. Stage: {service.STAGE_LABELS[o.stage]}")
            )
        for i in d.inspections[:8]:
            events.append((i.ts, "Inspection" + (" (archive)" if i.is_history else ""), i.finding.value))
        events.sort(key=lambda e: e[0], reverse=True)
        if not events:
            c.empty_state("Nothing recorded for this drain yet.", "history")
            return
        with ui.column().classes("w-full gap-0"):
            for ts, title, detail in events[:30]:
                with ui.row().classes("w-full no-wrap gap-3 py-2").style("border-bottom:1px solid var(--border)"):
                    ui.label(f"{ts:%d %b, %H:%M}").classes("dw-xs dw-mono dw-muted w-[92px] shrink-0 pt-[2px]")
                    with ui.column().classes("gap-0"):
                        ui.label(title).classes("dw-small font-semibold")
                        ui.label(detail).classes("dw-xs dw-muted")

    # ------------------------------------------------------------ actions

    def _dispatch(self, drain_id: str) -> None:
        order, crew = service.dispatch(drain_id, self.page.username)
        if crew:
            ui.notify(f"{crew.name} sent to {drain_id}. Work order {order.id}.", type="positive")
        else:
            ui.notify(
                f"Work order {order.id} created. Every crew is busy, so it waits in Pending dispatch.", type="warning"
            )
        self._render()

    def _false_alarm(self, drain_id: str) -> None:
        closed = service.mark_false_alarm(drain_id, self.page.username)
        ui.notify(
            f"{drain_id} marked as a false alarm. {closed} report{'s' if closed != 1 else ''} closed.", type="info"
        )
        self._render()
