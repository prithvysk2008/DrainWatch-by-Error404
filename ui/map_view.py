"""The drain network map: a schematic city drawn with ECharts (no map tiles, works offline).

This is where the design spends its boldness. In dark mode pipes glow, flow direction is animated
slowly and critical drains pulse. Live updates send only the series, so zoom and pan survive.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass, field

from nicegui import ui

from drainwatch import service
from drainwatch.theme import FONT, MONO, Palette, band_color, fill_color

BAND_SIZE = {"critical": 15, "high": 12, "medium": 9, "low": 7}
FILL_SIZE = {"critical": 14, "warning": 12, "normal": 8, "unknown": 7}


@dataclass
class MapLayers:
    flow: bool = True
    zones: bool = True
    reports: bool = True
    sensors: bool = False
    labels: int = 6  # how many top-priority drains get an id label


@dataclass
class MapState:
    color_by: str = "priority"  # priority | level
    status_filter: str = "all"  # all | critical | warning | normal  (level mode) or band names
    search: str = ""
    layers: MapLayers = field(default_factory=MapLayers)
    selected: str | None = None
    routes: list[tuple[str, list[tuple[float, float]], list[str]]] = field(default_factory=list)
    zone_id: str | None = None


def _tip(lines: list[str]) -> str:
    return "<br/>".join(lines)


class NetworkMap:
    def __init__(
        self,
        palette: Callable[[], Palette],
        reduced_motion: Callable[[], bool],
        on_select: Callable[[str], None] | None = None,
        state: MapState | None = None,
    ) -> None:
        self._palette = palette
        self._reduced = reduced_motion
        self._on_select = on_select
        self.state = state or MapState()
        self._geometry = service.map_geometry()
        with ui.element("div").classes("dw-map-frame w-full h-full") as self.frame:
            self.frame.props(
                'role="img" aria-label="Schematic map of the drain network. Use the priority list '
                'for the same information as text."'
            )
            self.chart = ui.echart(self._options(full=True), on_point_click=self._clicked).classes("dw-map-canvas")

    # ------------------------------------------------------------ public

    def refresh(self) -> None:
        """Live data changed: send the series only, keeping the viewer's zoom and pan."""
        options = self._options(full=True)
        self.chart._props["options"] = options
        self.chart.run_chart_method("setOption", {"series": options["series"]})

    def restyle(self) -> None:
        """Theme or motion setting changed: redraw everything."""
        self.chart._props["options"] = self._options(full=True)
        self.chart.update()

    def reset_view(self) -> None:
        self.chart.run_chart_method("dispatchAction", {"type": "dataZoom", "start": 0, "end": 100})

    def select(self, drain_id: str | None) -> None:
        self.state.selected = drain_id
        self.refresh()

    # ------------------------------------------------------------ internals

    def _clicked(self, e) -> None:
        data = e.data if isinstance(e.data, dict) else {}
        drain_id = data.get("id")
        if drain_id and self._on_select:
            self._on_select(drain_id)

    def _visible(self, row: service.DrainRow) -> bool:
        st = self.state
        if st.zone_id and row.info.zone_id != st.zone_id:
            return False
        if st.search:
            q = st.search.lower()
            if q not in row.info.id.lower() and q not in row.info.name.lower():
                return False
        if st.status_filter != "all":
            sc = row.score
            assert sc is not None
            key = sc.fill_status.value if st.color_by == "level" else sc.band.value
            if key != st.status_filter:
                return False
        return True

    def _options(self, full: bool) -> dict:
        p = self._palette()
        reduced = self._reduced()
        g = self._geometry
        st = self.state
        rows = service.drain_rows()
        visible = [r for r in rows if self._visible(r)]
        visible_ids = {r.info.id for r in visible}
        series: list[dict] = []

        # 0 city blocks (streets are the gaps between them)
        series.append(
            {
                "type": "line",
                "name": "blocks",
                "data": [],
                "silent": True,
                "z": 1,
                "markArea": {
                    "silent": True,
                    "itemStyle": {"color": p.map_block, "borderColor": p.map_block_edge, "borderWidth": 1},
                    "data": [[{"coord": [b[0], b[1]]}, {"coord": [b[2], b[3]]}] for b in g.blocks],
                },
            }
        )
        # 1 river
        series.append(
            {
                "type": "line",
                "name": "river",
                "data": [list(pt) for pt in g.river],
                "symbol": "none",
                "silent": True,
                "z": 2,
                "smooth": 0.3,
                "lineStyle": {"color": p.map_river_edge, "width": 2},
                "areaStyle": {"color": p.map_river, "opacity": 1, "origin": "start"},
            }
        )
        # 2 zone boundaries and 3 zone labels
        series.append(
            {
                "type": "lines",
                "name": "zones",
                "coordinateSystem": "cartesian2d",
                "silent": True,
                "z": 3,
                "polyline": False,
                "data": [{"coords": [list(a), list(b)]} for a, b in g.zone_lines] if st.layers.zones else [],
                "lineStyle": {"color": p.zone_line, "width": 1.5, "type": [8, 6], "opacity": 1},
            }
        )
        series.append(
            {
                "type": "scatter",
                "name": "zone labels",
                "silent": True,
                "z": 3,
                "symbolSize": 0,
                "data": [{"value": [x, y], "name": name} for name, x, y in g.zone_labels] if st.layers.zones else [],
                "label": {
                    "show": True,
                    "formatter": "{b}",
                    "color": p.zone_label,
                    "fontFamily": FONT,
                    "fontSize": 12,
                    "fontWeight": 600,
                    "align": "left",
                },
            }
        )
        # 4 laterals, 5 trunks
        laterals, trunks = [], []
        for a, b in service.network_edges():
            item = {"coords": [[a.x, a.y], [b.x, b.y]]}
            (trunks if a.is_trunk and b.is_trunk else laterals).append(item)
        glow = {"shadowBlur": 8, "shadowColor": p.pipe_glow} if p.dark else {}
        series.append(
            {
                "type": "lines",
                "name": "laterals",
                "coordinateSystem": "cartesian2d",
                "silent": True,
                "z": 4,
                "data": laterals,
                "lineStyle": {"color": p.pipe, "width": 1.6, "opacity": 0.85, **glow},
            }
        )
        series.append(
            {
                "type": "lines",
                "name": "trunks",
                "coordinateSystem": "cartesian2d",
                "silent": True,
                "z": 4,
                "data": trunks,
                "lineStyle": {"color": p.pipe_trunk, "width": 3.2, "opacity": 0.95, **glow},
            }
        )
        # 6 flow direction (dark mode, motion allowed)
        flow_on = st.layers.flow and p.dark and not reduced
        series.append(
            {
                "type": "lines",
                "name": "flow",
                "coordinateSystem": "cartesian2d",
                "silent": True,
                "z": 5,
                "data": (laterals + trunks) if flow_on else [],
                "lineStyle": {"opacity": 0, "width": 0},
                "effect": {
                    "show": flow_on,
                    "constantSpeed": 26,
                    "symbol": "arrow",
                    "symbolSize": 5,
                    "trailLength": 0,
                    "color": "#a5f3fc",
                    "loop": True,
                },
            }
        )
        # 7 report heat
        reports = service.open_reports() if st.layers.reports else []
        series.append(
            {
                "type": "scatter",
                "name": "reports",
                "silent": True,
                "z": 6,
                "data": [
                    {"value": [r.x_m, r.y_m]}
                    for r in reports
                    if not st.zone_id or service.drain_info(r.drain_id).zone_id == st.zone_id
                ],
                "symbolSize": 46,
                "itemStyle": {"color": p.warning, "opacity": 0.16},
            }
        )
        # 8 outfalls
        series.append(
            {
                "type": "scatter",
                "name": "outfalls",
                "z": 7,
                "symbol": "roundRect",
                "symbolSize": [16, 10],
                "itemStyle": {"color": p.map_river_edge, "borderColor": p.map_bg, "borderWidth": 2},
                "data": [
                    {"value": [o.x, o.y], "name": o.name, "tooltip": {"formatter": html.escape(o.name)}}
                    for o in service.outfalls()
                ],
                "label": {"show": False},
            }
        )

        # 9..13 drains by category
        top_ids = [r.info.id for r in visible if r.score and r.score.band.value == "critical"][: st.layers.labels]
        if not top_ids:
            top_ids = [r.info.id for r in visible if r.score and r.score.band.value == "high"][
                : min(3, st.layers.labels)
            ]
        groups: dict[str, list[dict]] = {}
        for r in rows:
            if r.info.id not in visible_ids:
                continue
            sc = r.score
            assert sc is not None
            if st.color_by == "level":
                key = sc.fill_status.value
                color = fill_color(p, key)
                size = FILL_SIZE[key]
            else:
                key = sc.band.value
                color = band_color(p, key)
                size = BAND_SIZE[key]
            fill_text = f"{sc.fill_pct:.0f}% full" if sc.fill_pct is not None and sc.sensor_ok else "No reading"
            item = {
                "id": r.info.id,
                "name": r.info.id,
                "value": [r.info.x, r.info.y],
                "symbolSize": size,
                "itemStyle": {
                    "color": color if (st.color_by != "level" or key != "unknown") else p.map_bg,
                    "borderColor": color if key == "unknown" else p.map_bg,
                    "borderWidth": 2,
                },
                "tooltip": {
                    "formatter": _tip(
                        [
                            f"<b>{r.info.id}</b> {html.escape(r.info.name)}",
                            f"{html.escape(r.info.zone_name)}, {html.escape(r.info.ward)}",
                            f"Priority {sc.score:.0f} ({sc.band.value}). {html.escape(sc.label.value)}",
                            f"{fill_text}",
                        ]
                    )
                },
            }
            if r.info.id in top_ids:
                item["label"] = {
                    "show": True,
                    "formatter": r.info.id,
                    "position": "right",
                    "distance": 8,
                    "color": p.text,
                    "fontFamily": MONO,
                    "fontSize": 11,
                    "fontWeight": 600,
                    "backgroundColor": p.card,
                    "padding": [2, 4],
                    "borderRadius": 3,
                    "borderColor": p.border,
                    "borderWidth": 1,
                }
            if st.layers.sensors and r.info.has_sensor:
                item["symbol"] = "rect"
            groups.setdefault(key, []).append(item)

        if st.color_by == "level":
            order = [("normal", None), ("unknown", None), ("warning", 2.4), ("critical", 1.8)]
        else:
            order = [("low", None), ("medium", None), ("high", 2.4), ("critical", 1.8)]
        for key, period in order:
            pulse = period is not None and not reduced
            s = {
                "type": "effectScatter" if pulse else "scatter",
                "name": key,
                "z": 8 + (2 if key == "critical" else 1 if period else 0),
                "data": groups.get(key, []),
                "emphasis": {"scale": 1.4},
                "cursor": "pointer",
            }
            if pulse:
                s.update(
                    {
                        "rippleEffect": {
                            "period": period,
                            "scale": 3.0 if key == "critical" else 2.3,
                            "brushType": "stroke",
                            "number": 2,
                        },
                        "showEffectOn": "render",
                    }
                )
            series.append(s)

        # 13 selected ring
        sel = service.drain_info(st.selected) if st.selected else None
        series.append(
            {
                "type": "scatter",
                "name": "selected",
                "silent": True,
                "z": 12,
                "symbol": "circle",
                "symbolSize": 30,
                "itemStyle": {"color": "transparent", "borderColor": p.accent, "borderWidth": 2.5},
                "data": [[sel.x, sel.y]] if sel else [],
            }
        )
        # 14 crew routes, 15 route stops
        route_lines, stops = [], []
        for crew_name, coords, stop_ids in st.routes:
            if len(coords) >= 2:
                route_lines.append({"coords": [list(c) for c in coords]})
            for n, (c, sid) in enumerate(zip(coords[1:], stop_ids, strict=False), start=1):
                stops.append(
                    {
                        "value": list(c),
                        "name": sid,
                        "label": {"formatter": str(n)},
                        "tooltip": {"formatter": f"{html.escape(crew_name)}, stop {n}: {sid}"},
                    }
                )
            if coords:
                stops.append(
                    {
                        "value": list(coords[0]),
                        "name": crew_name,
                        "symbol": "rect",
                        "symbolSize": 14,
                        "label": {
                            "formatter": crew_name,
                            "position": "top",
                            "color": p.text,
                            "backgroundColor": p.card,
                            "padding": [2, 4],
                            "borderRadius": 3,
                        },
                        "tooltip": {"formatter": f"{html.escape(crew_name)} base"},
                    }
                )
        series.append(
            {
                "type": "lines",
                "name": "routes",
                "coordinateSystem": "cartesian2d",
                "polyline": True,
                "silent": True,
                "z": 13,
                "data": route_lines,
                "lineStyle": {"color": p.info, "width": 2.5, "opacity": 0.9},
            }
        )
        series.append(
            {
                "type": "scatter",
                "name": "stops",
                "z": 14,
                "symbolSize": 18,
                "data": stops,
                "itemStyle": {"color": p.info, "borderColor": p.map_bg, "borderWidth": 2},
                "label": {"show": True, "color": "#ffffff", "fontFamily": MONO, "fontSize": 10, "fontWeight": 700},
            }
        )

        options = {
            "backgroundColor": p.map_bg,
            "animation": False,
            "grid": {"left": 0, "right": 0, "top": 0, "bottom": 0},
            "xAxis": {"type": "value", "min": 0, "max": g.width, "show": False},
            "yAxis": {"type": "value", "min": 0, "max": g.height, "show": False},
            "dataZoom": [
                {"type": "inside", "xAxisIndex": 0, "filterMode": "none", "minSpan": 15},
                {"type": "inside", "yAxisIndex": 0, "filterMode": "none", "minSpan": 15},
            ],
            "tooltip": {
                "trigger": "item",
                "confine": True,
                "backgroundColor": p.tooltip_bg,
                "borderColor": p.tooltip_border,
                "padding": [8, 10],
                "textStyle": {"color": p.text, "fontFamily": FONT, "fontSize": 12},
                "extraCssText": "border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.2);",
            },
            "series": series,
        }
        return options


def legend(color_by: str, warning_pct: float, critical_pct: float) -> None:
    """Legend with text labels and thresholds. Marker size also differs by severity."""
    if color_by == "level":
        items = [
            ("--normal", 8, f"Normal, below {warning_pct:.0f}%"),
            ("--warning", 12, f"Warning, {warning_pct:.0f} to {critical_pct:.0f}%"),
            ("--critical", 14, f"Critical, {critical_pct:.0f}% or more"),
            ("--unknown", 8, "No reading"),
        ]
    else:
        items = [
            ("--critical", 14, "Critical"),
            ("--high", 12, "High"),
            ("--medium", 9, "Medium"),
            ("--normal", 7, "Low"),
        ]
    with ui.element("div").classes("dw-map-legend"):
        for var, size, text in items:
            with ui.element("span").classes("inline-flex items-center"):
                ui.element("span").classes("sym").style(f"width:{size + 4}px;height:{size + 4}px;background:var({var})")
                ui.label(text)
