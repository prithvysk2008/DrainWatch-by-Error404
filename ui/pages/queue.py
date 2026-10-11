"""Priority risk queue: ranked drains with the score breakdown, as a table or as severity columns."""

from __future__ import annotations

from nicegui import app, ui

from drainwatch import service
from ui import components as c
from ui.drawer import DrainDrawer
from ui.layout import shell

COLUMNS = [
    {"name": "rank", "label": "Rank", "field": "rank", "align": "left", "sortable": True},
    {"name": "drain", "label": "Drain, street and zone", "field": "id", "align": "left", "sortable": True},
    {"name": "level", "label": "Water level", "field": "fill_sort", "align": "left", "sortable": True},
    {"name": "silt", "label": "Silt", "field": "silt", "align": "right", "sortable": True},
    {"name": "reports", "label": "Reports", "field": "reports", "align": "right", "sortable": True},
    {"name": "score", "label": "Priority score", "field": "score", "align": "left", "sortable": True},
    {"name": "label", "label": "Classification", "field": "label", "align": "left"},
    {"name": "action", "label": "Action", "field": "action", "align": "right"},
]

DRAIN_SLOT = r"""
<q-td :props="props">
  <div class="dw-mono font-semibold">{{ props.row.id }}</div>
  <div class="dw-xs" style="min-width:220px;max-width:300px;white-space:normal">{{ props.row.name }}</div>
  <div class="dw-xs dw-muted">{{ props.row.zone }}, {{ props.row.ward }}</div>
</q-td>"""

LEVEL_SLOT = r"""
<q-td :props="props">
  <span :class="'dw-badge is-soft tone-' + props.row.fill_tone">
    <q-icon :name="props.row.fill_icon" aria-hidden="true" />{{ props.row.fill_text }}
  </span>
</q-td>"""
SCORE_SLOT = r"""
<q-td :props="props">
  <div class="flex items-center gap-2 no-wrap">
    <span :class="'dw-badge is-solid tone-' + props.row.band" style="min-width:78px">
      <q-icon :name="props.row.band_icon" aria-hidden="true" />{{ props.row.band_text }}
    </span>
    <div class="dw-scorebar" style="min-width:90px">
      <div class="track">
        <div class="fill" :style="{width: props.row.score + '%', background: 'var(' + props.row.band_var + ')'}">
        </div>
      </div>
      <span class="dw-mono dw-small font-semibold" style="width:28px;text-align:right">{{ props.row.score_text }}</span>
    </div>
  </div>
</q-td>"""
LABEL_SLOT = r"""
<q-td :props="props">
  <div class="flex items-center gap-1 no-wrap dw-small" :title="props.row.label">
    <q-icon :name="props.row.label_icon" size="16px" aria-hidden="true" />{{ props.row.label_short }}
  </div>
  <div class="dw-xs dw-muted">Confidence {{ props.row.confidence }}</div>
</q-td>"""
ACTION_SLOT = r"""
<q-td :props="props">
  <q-btn unelevated no-caps dense class="dw-btn-secondary px-3" :label="props.row.action"
         :disable="props.row.crew_sent" @click.stop="() => $parent.$emit('dispatch', props.row)" />
</q-td>"""


def table_rows(zone_id: str | None, view: str, label: str) -> list[dict]:
    rows = []
    for r in service.drain_rows(zone_id):
        sc = r.score
        assert sc is not None
        if view == "action" and sc.band.value not in ("critical", "high"):
            continue
        if view == "no_order" and r.open_order is not None:
            continue
        if label != "all" and sc.label.value != label:
            continue
        fill_known = sc.sensor_ok and sc.fill_pct is not None
        crew_sent = bool(r.open_order and r.open_order.crew_id)
        rows.append(
            {
                "rank": r.rank,
                "id": r.info.id,
                "name": r.info.name,
                "zone": r.info.zone_name,
                "ward": r.info.ward,
                "fill_sort": sc.fill_pct if fill_known else -1,
                "fill_tone": c.FILL_TONE[sc.fill_status.value],
                "fill_icon": c.FILL_ICON[sc.fill_status.value],
                "fill_text": f"{c.FILL_TEXT[sc.fill_status.value]} {sc.fill_pct:.0f}%" if fill_known else "No reading",
                "silt": f"{r.info.silt_pct:.0f}%",
                "reports": r.report_count,
                "score": sc.score,
                "score_text": f"{sc.score:.0f}",
                "band": sc.band.value,
                "band_icon": c.BAND_ICON[sc.band.value],
                "band_text": c.BAND_TEXT[sc.band.value],
                "band_var": c.band_var(sc.band.value),
                "label": sc.label.value,
                "label_short": c.LABEL_SHORT[sc.label.value],
                "label_icon": c.LABEL_ICON[sc.label.value],
                "confidence": f"{sc.confidence * 100:.0f}%",
                "crew_sent": crew_sent,
                "action": "Crew sent" if crew_sent else "Dispatch crew",
            }
        )
    return rows


@ui.page("/queue")
async def queue_page(drain: str | None = None) -> None:
    page = await shell("queue", "Priority risk queue")
    if page is None:
        return
    drawer = DrainDrawer(page)
    prefs = app.storage.user.setdefault("queue", {"layout": "table", "view": "all", "label": "all"})

    with ui.element("main").classes("dw-page w-full"):
        with ui.element("div").classes("dw-page-head"):
            with ui.column().classes("gap-1 max-w-[860px]"):
                ui.html('<h1 class="dw-h1">Priority-based flood risk assessment matrix</h1>', sanitize=False)
                ui.label(
                    "Score = water level 40 + rainfall 30 + inspection history 20 + reports 10, "
                    "multiplied by 1.2 when reports and the sensor agree, plus up to 4 for low ground or a "
                    "critical site."
                ).classes("dw-muted")

                @ui.refreshable
                def count_line() -> None:
                    k = service.kpis(page.zone_id)
                    high = sum(1 for r in service.drain_rows(page.zone_id) if r.score.band.value == "high")
                    n = k["critical"] + high
                    ui.label(
                        f"{n} priority intervention{'s' if n != 1 else ''} identified: "
                        f"{k['critical']} critical, {high} high."
                    ).classes("font-semibold mt-1")

                count_line()
            with ui.row().classes("gap-2"):
                c.button("Recompute index", icon="refresh", on_click=lambda: recompute()).classes(
                    "dw-btn-secondary"
                ).props("unelevated no-caps")
                c.button("Export dispatch batch", icon="download", on_click=lambda: export()).classes(
                    "dw-btn-primary"
                ).props("unelevated no-caps")

        with ui.row().classes("items-end gap-3 w-full mb-3 wrap"):
            with ui.column().classes("gap-1"):
                ui.label("Layout").classes("dw-xs dw-muted")
                layout_toggle = (
                    ui.toggle(
                        {"table": "Table", "board": "Board"},
                        value=prefs["layout"],
                        on_change=lambda e: set_pref("layout", e.value),
                    )
                    .props("no-caps unelevated toggle-color=dw-on toggle-text-color=dw-on-text")
                    .classes("dw-seg")
                )
            with ui.column().classes("gap-1"):
                ui.label("Show").classes("dw-xs dw-muted")
                ui.toggle(
                    {"all": "All drains", "action": "Critical and high", "no_order": "No work order yet"},
                    value=prefs["view"],
                    on_change=lambda e: set_pref("view", e.value),
                ).props("no-caps unelevated toggle-color=dw-on toggle-text-color=dw-on-text").classes("dw-seg")
            labels = {"all": "All classifications"} | {lab: lab for lab in c.LABEL_ICON}
            ui.select(
                labels, value=prefs["label"], label="Classification", on_change=lambda e: set_pref("label", e.value)
            ).props("outlined dense options-dense").classes("min-w-[260px]")
        _ = layout_toggle

        @ui.refreshable
        def body() -> None:
            rows = table_rows(page.zone_id, prefs["view"], prefs["label"])
            if not rows:
                c.empty_state("No drains match these filters. Choose All drains to see the full ranking.", "filter_alt")
                return
            if prefs["layout"] == "table":
                table = (
                    ui.table(rows=rows, columns=COLUMNS, row_key="id", pagination={"rowsPerPage": 25})
                    .classes("dw-table dw-card w-full")
                    .props("flat")
                )
                table.add_slot("body-cell-drain", DRAIN_SLOT)
                table.add_slot("body-cell-level", LEVEL_SLOT)
                table.add_slot("body-cell-score", SCORE_SLOT)
                table.add_slot("body-cell-label", LABEL_SLOT)
                table.add_slot("body-cell-action", ACTION_SLOT)
                table.on("rowClick", lambda e: drawer.open(e.args[1]["id"]))
                table.on("dispatch", lambda e: dispatch(e.args["id"]))
                holder["table"] = table
            else:
                board(rows)

        holder: dict = {}
        body()

    def board(rows: list[dict]) -> None:
        with ui.element("div").classes("grid gap-4 w-full grid-cols-1 md:grid-cols-2 xl:grid-cols-4"):
            for band in ("critical", "high", "medium", "low"):
                items = [r for r in rows if r["band"] == band]
                with (
                    ui.element("section")
                    .classes("dw-column flex flex-col")
                    .props(f'aria-label="{c.BAND_TEXT[band]}, {len(items)} drains"')
                ):
                    with ui.element("div").classes("dw-column-head"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon(c.BAND_ICON[band]).style(f"color:var({c.band_var(band)})")
                            ui.label(c.BAND_TEXT[band]).classes("dw-card-title")
                        ui.label(str(len(items))).classes("dw-count")
                    with ui.column().classes("p-3 gap-3 w-full max-h-[70vh] overflow-y-auto"):
                        if not items:
                            c.empty_state(f"No {c.BAND_TEXT[band].lower()} drains right now.", "check")
                        for r in items[:30]:
                            with (
                                ui.element("button")
                                .classes(f"dw-card-item edge-{band} w-full text-left")
                                .props(f'type="button" aria-label="Open {r["id"]}"')
                                .on("click", lambda d=r["id"]: drawer.open(d))
                            ):
                                with ui.row().classes("items-center justify-between w-full no-wrap"):
                                    with ui.row().classes("items-center gap-1 no-wrap min-w-0"):
                                        ui.icon(c.LABEL_ICON.get(r["label"], "info")).classes("text-base dw-muted")
                                        ui.label(r["label"]).classes("dw-xs dw-muted truncate")
                                    ui.label(r["score_text"]).classes("dw-mono font-semibold")
                                ui.label(f"{r['id']} {r['name']}").classes("font-semibold text-[13.5px] mt-1")
                                with ui.row().classes("items-center justify-between w-full mt-2 dw-xs dw-muted"):
                                    ui.label(f"{r['zone']}, {r['ward']}")
                                    with ui.row().classes("items-center gap-3 no-wrap"):
                                        ui.label(r["fill_text"])
                                        ui.label(f"{r['reports']} report{'s' if r['reports'] != 1 else ''}")
                        if len(items) > 30:
                            ui.label(f"And {len(items) - 30} more. Switch to Table to see them all.").classes(
                                "dw-xs dw-muted"
                            )

    def set_pref(key: str, value: str) -> None:
        prefs[key] = value
        app.storage.user["queue"] = prefs
        body.refresh()

    def recompute() -> None:
        body.refresh()
        count_line.refresh()
        ui.notify("Priority index recomputed from the latest readings and reports.", type="info")

    def export() -> None:
        ui.download.content(service.dispatch_batch_csv(), "drainwatch-dispatch-batch.csv", "text/csv")
        ui.notify("Dispatch batch exported: the top 20 drains with scores and reasons.", type="positive")

    def dispatch(drain_id: str) -> None:
        order, crew = service.dispatch(drain_id, page.username)
        if crew:
            ui.notify(f"{crew.name} sent to {drain_id}. Work order {order.id}.", type="positive")
        else:
            ui.notify(
                f"Work order {order.id} created. Every crew is busy, so it waits in Pending dispatch.", type="warning"
            )

    def live() -> None:
        count_line.refresh()
        table = holder.get("table")
        if prefs["layout"] == "table" and table is not None and not table.is_deleted:
            table.rows[:] = table_rows(page.zone_id, prefs["view"], prefs["label"])
            table.update()
        else:
            body.refresh()

    page.on_live(live)
    if drain and service.drain_info(drain):
        drawer.open(drain)
