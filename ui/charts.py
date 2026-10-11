"""ECharts option builders. Thin marks, hairline grids, one y-axis per panel, text in text tokens."""

from __future__ import annotations

from drainwatch.theme import FONT, MONO, Palette, axis, chart_base

HEAVY_RAIN_MM_10MIN = 4.0  # 24 mm per hour


def _bar_item(value: float, color: str, opacity: float = 1.0) -> dict:
    return {"value": value, "itemStyle": {"color": color, "opacity": opacity, "borderRadius": [4, 4, 0, 0]}}


def rainfall(series: list[tuple[str, float, bool]], p: Palette, reduced_motion: bool) -> dict:
    """City rainfall per 10 minutes. Steps not reached yet show as a faint scenario forecast."""
    labels = [s[0] for s in series]
    data = []
    for _, value, future in series:
        color = p.warning if value >= HEAVY_RAIN_MM_10MIN else p.accent
        data.append(_bar_item(round(value, 2), color, 0.28 if future else 1.0))
    return {
        **chart_base(p),
        "animation": not reduced_motion,
        "grid": {"left": 34, "right": 6, "top": 10, "bottom": 22},
        "xAxis": axis(
            p,
            type="category",
            data=labels,
            splitLine={"show": False},
            axisLabel={"color": p.muted, "fontSize": 11, "interval": 5, "fontFamily": FONT},
        ),
        "yAxis": axis(
            p, type="value", min=0, splitNumber=3, axisLabel={"color": p.muted, "fontSize": 11, "fontFamily": FONT}
        ),
        "tooltip": {**chart_base(p)["tooltip"], "trigger": "axis", "axisPointer": {"type": "shadow"}},
        "series": [
            {"type": "bar", "name": "Rain, mm per 10 min", "data": data, "barMaxWidth": 12, "barCategoryGap": "30%"}
        ],
    }


def readings(
    times: list[str],
    observed: list[float | None],
    expected: list[float],
    spread: list[float],
    rain: list[float],
    depth_cm: float,
    warning_pct: float,
    critical_pct: float,
    p: Palette,
) -> dict:
    """Two panels on one time axis: water level (observed vs expected) above, rain below."""
    lower = [round(max(e - s, 0), 1) for e, s in zip(expected, spread, strict=True)]
    band = [round(2 * s, 1) for s in spread]
    warn_cm = depth_cm * warning_pct / 100
    crit_cm = depth_cm * critical_pct / 100
    return {
        **chart_base(p),
        "tooltip": {**chart_base(p)["tooltip"], "trigger": "axis"},
        "axisPointer": {"link": [{"xAxisIndex": "all"}], "lineStyle": {"color": p.border}},
        "grid": [
            {"left": 44, "right": 12, "top": 14, "height": "56%"},
            {"left": 44, "right": 12, "top": "76%", "bottom": 24},
        ],
        "xAxis": [
            axis(
                p,
                type="category",
                data=times,
                gridIndex=0,
                boundaryGap=False,
                axisLabel={"show": False},
                splitLine={"show": False},
            ),
            axis(
                p,
                type="category",
                data=times,
                gridIndex=1,
                splitLine={"show": False},
                axisLabel={"color": p.muted, "fontSize": 11, "interval": "auto"},
            ),
        ],
        "yAxis": [
            axis(
                p,
                type="value",
                gridIndex=0,
                min=0,
                max=int(-(-depth_cm // 50) * 50),
                name="cm",
                splitNumber=4,
                nameGap=8,
            ),
            axis(p, type="value", gridIndex=1, min=0, name="mm", splitNumber=2, nameGap=6),
        ],
        "series": [
            {
                "type": "line",
                "name": "lower",
                "data": lower,
                "stack": "band",
                "symbol": "none",
                "lineStyle": {"opacity": 0},
                "tooltip": {"show": False},
                "silent": True,
            },
            {
                "type": "line",
                "name": "Normal range",
                "data": band,
                "stack": "band",
                "symbol": "none",
                "lineStyle": {"opacity": 0},
                "areaStyle": {"color": p.expected, "opacity": 0.14},
                "silent": True,
                "tooltip": {"show": False},
            },
            {
                "type": "line",
                "name": "Expected for this rain",
                "data": expected,
                "symbol": "none",
                "lineStyle": {"color": p.expected, "width": 2, "type": [4, 4]},
                "itemStyle": {"color": p.expected},
            },
            {
                "type": "line",
                "name": "Observed",
                "data": observed,
                "symbol": "circle",
                "symbolSize": 5,
                "showSymbol": False,
                "connectNulls": False,
                "lineStyle": {"color": p.accent, "width": 2},
                "itemStyle": {"color": p.accent},
                "markLine": {
                    "silent": True,
                    "symbol": "none",
                    "label": {"color": p.muted, "fontSize": 11, "position": "insideEndTop"},
                    "data": [
                        {
                            "yAxis": round(warn_cm),
                            "name": "Warning",
                            "lineStyle": {"color": p.warning, "type": "solid", "width": 1, "opacity": 0.7},
                            "label": {"formatter": "Warning", "position": "insideStartTop"},
                        },
                        {
                            "yAxis": round(crit_cm),
                            "name": "Critical",
                            "lineStyle": {"color": p.critical, "type": "solid", "width": 1, "opacity": 0.7},
                            "label": {"formatter": "Critical"},
                        },
                    ],
                },
            },
            {
                "type": "bar",
                "name": "Rain, mm per 10 min",
                "data": rain,
                "xAxisIndex": 1,
                "yAxisIndex": 1,
                "itemStyle": {"color": p.info, "borderRadius": [3, 3, 0, 0]},
                "barMaxWidth": 8,
            },
        ],
    }


def contributions(parts: dict[str, float], p: Palette) -> dict:
    """Points each factor added to the score. One series, one colour, values at the bar tips."""
    items = [(k, v) for k, v in parts.items() if v > 0 or k in ("Water level", "Rainfall", "History", "Reports")]
    items.reverse()
    return {
        **chart_base(p),
        "grid": {"left": 8, "right": 40, "top": 4, "bottom": 4, "containLabel": True},
        "xAxis": axis(p, type="value", show=False, max=max([40.0] + [v for _, v in items])),
        "yAxis": axis(
            p,
            type="category",
            data=[k for k, _ in items],
            axisLine={"show": False},
            axisLabel={"color": p.text, "fontSize": 12, "fontFamily": FONT},
        ),
        "tooltip": {"show": False},
        "series": [
            {
                "type": "bar",
                "data": [round(v, 1) for _, v in items],
                "barMaxWidth": 14,
                "itemStyle": {"color": p.accent, "borderRadius": [0, 4, 4, 0]},
                "label": {
                    "show": True,
                    "position": "right",
                    "color": p.text,
                    "fontFamily": MONO,
                    "fontSize": 11,
                    "formatter": "{c}",
                },
                "showBackground": True,
                "backgroundStyle": {"color": p.grid, "borderRadius": [0, 4, 4, 0]},
            }
        ],
    }


def sparkline(values: list[float | None], p: Palette, color: str | None = None) -> dict:
    return {
        "backgroundColor": "transparent",
        "animation": False,
        "grid": {"left": 0, "right": 0, "top": 2, "bottom": 2},
        "xAxis": {"type": "category", "show": False, "boundaryGap": False, "data": list(range(len(values)))},
        "yAxis": {"type": "value", "show": False, "min": 0},
        "series": [
            {
                "type": "line",
                "data": values,
                "symbol": "none",
                "lineStyle": {"color": color or p.accent, "width": 2},
                "areaStyle": {"color": color or p.accent, "opacity": 0.1},
            }
        ],
    }


def time_panel(
    times: list[str],
    values: list[float],
    name: str,
    unit: str,
    p: Palette,
    color: str,
    bars: bool = False,
    reference: list[float] | None = None,
    show_x: bool = True,
) -> dict:
    """One measure over the storm. Analytics stacks two of these instead of using a second y-axis."""
    series = []
    if reference is not None:
        series.append(
            {
                "type": "line",
                "name": "Expected without faults",
                "data": reference,
                "symbol": "none",
                "lineStyle": {"color": p.expected, "width": 2, "type": [4, 4]},
                "itemStyle": {"color": p.expected},
            }
        )
    if bars:
        series.append(
            {
                "type": "bar",
                "name": name,
                "data": values,
                "barMaxWidth": 10,
                "itemStyle": {"color": color, "borderRadius": [3, 3, 0, 0]},
            }
        )
    else:
        series.append(
            {
                "type": "line",
                "name": name,
                "data": values,
                "symbol": "none",
                "lineStyle": {"color": color, "width": 2},
                "itemStyle": {"color": color},
                "areaStyle": {"color": color, "opacity": 0.1},
            }
        )
    return {
        **chart_base(p),
        "tooltip": {**chart_base(p)["tooltip"], "trigger": "axis"},
        "grid": {"left": 44, "right": 12, "top": 22, "bottom": 24 if show_x else 8},
        "xAxis": axis(
            p,
            type="category",
            data=times,
            boundaryGap=bars,
            splitLine={"show": False},
            axisLabel={"color": p.muted, "fontSize": 11, "show": show_x},
        ),
        "yAxis": axis(p, type="value", min=0, name=unit, nameGap=8, splitNumber=3),
        "series": series,
    }


def hbar(rows: list[tuple[str, float]], p: Palette, unit: str = "", color: str | None = None) -> dict:
    """Ranked horizontal bars, single colour, value at the tip."""
    rows = list(reversed(rows))
    fmt = "{c}" + (f" {unit}" if unit else "")
    return {
        **chart_base(p),
        "grid": {"left": 8, "right": 56, "top": 4, "bottom": 4, "containLabel": True},
        "xAxis": axis(p, type="value", show=False),
        "yAxis": axis(
            p,
            type="category",
            data=[r[0] for r in rows],
            axisLine={"show": False},
            axisLabel={"color": p.text, "fontSize": 12},
        ),
        "tooltip": {"show": False},
        "series": [
            {
                "type": "bar",
                "data": [r[1] for r in rows],
                "barMaxWidth": 16,
                "itemStyle": {"color": color or p.accent, "borderRadius": [0, 4, 4, 0]},
                "label": {
                    "show": True,
                    "position": "right",
                    "color": p.text,
                    "fontFamily": MONO,
                    "fontSize": 11,
                    "formatter": fmt,
                },
            }
        ],
    }


def validation_bars(method: tuple[float, float], baseline: tuple[float, float], p: Palette) -> dict:
    """Method against a random ranking for precision at 10 and recall at 20. Two series, legend shown."""
    cats = ["Precision at 10", "Recall at 20"]
    return {
        **chart_base(p),
        "legend": {
            "top": 0,
            "left": 0,
            "itemWidth": 10,
            "itemHeight": 10,
            "textStyle": {"color": p.text},
            "data": ["Drain Watch ranking", "Random ranking"],
        },
        "grid": {"left": 40, "right": 8, "top": 44, "bottom": 24},
        "xAxis": axis(
            p, type="category", data=cats, splitLine={"show": False}, axisLabel={"color": p.text, "fontSize": 12}
        ),
        "yAxis": axis(
            p,
            type="value",
            min=0,
            max=1,
            splitNumber=4,
            axisLabel={"color": p.muted, "fontSize": 11, "formatter": "{value}"},
        ),
        "tooltip": {"show": False},
        "series": [
            {
                "type": "bar",
                "name": "Drain Watch ranking",
                "data": [{"value": round(v, 2), "label": {"formatter": f"{v:.2f}"}} for v in method],
                "barMaxWidth": 24,
                "barGap": "12%",
                "itemStyle": {"color": p.accent, "borderRadius": [4, 4, 0, 0]},
                "label": {"show": True, "position": "top", "color": p.text, "fontFamily": MONO, "fontSize": 11},
            },
            {
                "type": "bar",
                "name": "Random ranking",
                "data": [{"value": round(v, 2), "label": {"formatter": f"{v:.2f}"}} for v in baseline],
                "barMaxWidth": 24,
                "itemStyle": {"color": p.expected, "borderRadius": [4, 4, 0, 0]},
                "label": {"show": True, "position": "top", "color": p.text, "fontFamily": MONO, "fontSize": 11},
            },
        ],
    }
