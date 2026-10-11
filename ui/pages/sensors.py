"""Sensors and calibration: one threshold profile for the whole app, and the sensor registry."""

from __future__ import annotations

from nicegui import ui

from drainwatch import service
from ui import components as c
from ui.layout import shell

DIAG_TONE = {
    "Optimal": "ok",
    "Low battery": "warning",
    "Check antenna": "warning",
    "Stuck reading": "critical",
    "No data": "critical",
}
DIAG_ICON = {
    "Optimal": "check_circle",
    "Low battery": "battery_alert",
    "Check antenna": "network_check",
    "Stuck reading": "error",
    "No data": "error",
}

REGISTRY_COLUMNS = [
    {"name": "serial", "label": "Sensor", "field": "serial", "align": "left", "sortable": True},
    {"name": "drain", "label": "Drain", "field": "drain", "align": "left", "sortable": True},
    {"name": "battery", "label": "Battery", "field": "battery", "align": "right", "sortable": True},
    {"name": "signal", "label": "Signal", "field": "signal", "align": "right", "sortable": True},
    {"name": "offset", "label": "Calibration offset", "field": "offset", "align": "right"},
    {"name": "ping", "label": "Last reading", "field": "ping", "align": "right"},
    {"name": "diag", "label": "Diagnostics", "field": "diag", "align": "left", "sortable": True},
]
DRAIN_SLOT = r"""
<q-td :props="props">
  <div class="dw-mono font-semibold">{{ props.row.drain }}</div>
  <div class="dw-xs dw-muted">{{ props.row.drain_name }}</div>
</q-td>"""
BATTERY_SLOT = r"""
<q-td :props="props">
  <span class="dw-tabular" :style="props.row.battery < 20 ? 'color:var(--warning-ink);font-weight:600' : ''">
    {{ props.row.battery }}%</span>
</q-td>"""
SIGNAL_SLOT = r"""
<q-td :props="props">
  <span class="dw-tabular">{{ props.row.signal }} dBm</span>
  <div class="dw-xs dw-muted">{{ props.row.signal_text }}</div>
</q-td>"""
DIAG_SLOT = r"""
<q-td :props="props">
  <span :class="'dw-badge is-soft tone-' + props.row.diag_tone">
    <q-icon :name="props.row.diag_icon" aria-hidden="true" />{{ props.row.diag }}
  </span>
</q-td>"""


def registry_rows(problems_only: bool, zone_id: str | None) -> list[dict]:
    rows = []
    for r in service.sensor_rows():
        diag = r.diagnostic.value
        if problems_only and diag == "Optimal":
            continue
        if zone_id and r.drain.zone_id != zone_id:
            continue
        signal = r.sensor.signal_dbm
        rows.append(
            {
                "serial": r.sensor.serial,
                "drain": r.drain.id,
                "drain_name": r.drain.name,
                "battery": r.sensor.battery_pct,
                "signal": signal,
                "signal_text": "Strong" if signal >= -70 else "Fair" if signal >= -90 else "Weak",
                "offset": f"{r.sensor.calibration_offset_cm:+.1f} cm",
                "ping_sort": r.last_ping_min if r.last_ping_min is not None else 9999,
                "ping": "No readings"
                if r.last_ping_min is None
                else ("This step" if r.last_ping_min == 0 else f"{r.last_ping_min} min ago"),
                "diag": diag,
                "diag_tone": DIAG_TONE[diag],
                "diag_icon": DIAG_ICON[diag],
            }
        )
    return rows


@ui.page("/sensors")
async def sensors_page() -> None:
    page = await shell("sensors", "Sensors and calibration")
    if page is None:
        return
    th = service.thresholds()

    with ui.element("main").classes("dw-page w-full"):
        with ui.element("div").classes("dw-page-head"):
            with ui.column().classes("gap-1 max-w-[760px]"):
                ui.html('<h1 class="dw-h1">Sensors and calibration</h1>', sanitize=False)
                ui.label(
                    "One threshold profile drives the map legend, the badges and the sensor health counts. "
                    "Levels are a percent of each drain's depth."
                ).classes("dw-muted")
            c.button("Save calibration profile", icon="save", on_click=lambda: save()).classes("dw-btn-primary").props(
                "unelevated no-caps"
            )

        sliders = {}
        with ui.element("div").classes("grid gap-4 w-full grid-cols-1 md:grid-cols-3"):
            for key, title, note, lo, hi, var in (
                (
                    "unimpeded",
                    "Normal operating limit",
                    "Water flows freely below this level. Drawn as a reference line on charts.",
                    20,
                    60,
                    "--normal",
                ),
                (
                    "warning",
                    "Warning threshold",
                    "Drains above this show as Warning and raise an advisory.",
                    50,
                    90,
                    "--warning",
                ),
                (
                    "critical",
                    "Critical overflow threshold",
                    "Drains above this show as Critical and notify the control room.",
                    70,
                    99,
                    "--critical",
                ),
            ):
                with ui.element("section").classes("dw-card dw-card-pad"):
                    with ui.row().classes("items-center gap-2"):
                        ui.element("span").classes("dw-legend-dot").style(f"background:var({var})")
                        ui.label(title).classes("dw-card-title")
                    ui.label(note).classes("dw-small dw-muted mt-1")
                    with ui.row().classes("items-center gap-3 w-full mt-3 no-wrap"):
                        slider = (
                            ui.slider(min=lo, max=hi, step=1, value=getattr(th, key))
                            .props(f'aria-label="{title}"')
                            .classes("grow")
                        )
                        ui.label().bind_text_from(slider, "value", lambda v: f"{v:.0f}%").classes(
                            "font-semibold dw-tabular w-12 text-right"
                        )
                    sliders[key] = slider
        error = ui.label().classes("dw-small mt-2").style("color:var(--critical-ink)").props('role="alert"')

        with ui.element("section").classes("dw-card w-full mt-4 overflow-hidden"):
            with ui.row().classes("items-center justify-between w-full px-5 py-4"):

                @ui.refreshable
                def registry_head() -> None:
                    rows = service.sensor_rows()
                    problems = sum(1 for r in rows if r.diagnostic.value != "Optimal")
                    c.card_title(
                        f"Sensor registry, {len(rows)} water-level sensors",
                        f"{problems} need attention. Diagnostics come from each sensor's own data.",
                    )

                registry_head()
                problems_only = ui.switch(
                    "Show only sensors that need attention", value=False, on_change=lambda: update_table()
                )
            table = (
                ui.table(
                    rows=registry_rows(False, page.zone_id),
                    columns=REGISTRY_COLUMNS,
                    row_key="serial",
                    pagination={"rowsPerPage": 15},
                )
                .classes("dw-table w-full")
                .props("flat")
            )
            table.add_slot("body-cell-drain", DRAIN_SLOT)
            table.add_slot("body-cell-battery", BATTERY_SLOT)
            table.add_slot("body-cell-signal", SIGNAL_SLOT)
            table.add_slot("body-cell-diag", DIAG_SLOT)

    def save() -> None:
        try:
            service.save_thresholds(
                float(sliders["unimpeded"].value),
                float(sliders["warning"].value),
                float(sliders["critical"].value),
                page.username,
            )
        except ValueError as exc:
            error.set_text(str(exc))
            return
        error.set_text("")
        ui.notify("Calibration profile saved. The map, badges and sensor counts now use these levels.", type="positive")

    def update_table() -> None:
        table.rows[:] = registry_rows(problems_only.value, page.zone_id)
        table.update()

    def live() -> None:
        update_table()
        registry_head.refresh()

    page.on_live(live)
