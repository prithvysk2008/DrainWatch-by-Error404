"""Theme tokens for charts and the schematic map. CSS tokens live in static/css/drainwatch.css.

The two dicts mirror the CSS variables so canvas-drawn charts match the page in both themes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    dark: bool
    text: str
    muted: str
    faint: str
    card: str
    inset: str
    border: str
    grid: str
    accent: str
    accent_soft: str
    critical: str
    high: str
    medium: str
    normal: str
    warning: str
    info: str
    unknown: str
    expected: str  # neutral series for "normal behaviour"
    # map
    map_bg: str  # street surface
    map_block: str
    map_block_edge: str
    map_river: str
    map_river_edge: str
    pipe: str
    pipe_trunk: str
    pipe_glow: str
    zone_line: str
    zone_label: str
    tooltip_bg: str
    tooltip_border: str


DARK = Palette(
    dark=True,
    text="#f1f5f9",
    muted="#94a3b8",
    faint="#8092ab",
    card="#111827",
    inset="#0c1322",
    border="#1f293d",
    grid="#1c263a",
    accent="#14b8a6",
    accent_soft="rgba(20,184,166,0.12)",
    critical="#f43f5e",
    high="#fb923c",
    medium="#facc15",
    normal="#10b981",
    warning="#f59e0b",
    info="#38bdf8",
    unknown="#64748b",
    expected="#7d8aa0",
    map_bg="#060a14",
    map_block="#0d1527",
    map_block_edge="#16223a",
    map_river="#0a2236",
    map_river_edge="#1b5d80",
    pipe="#1c8fae",
    pipe_trunk="#22d3ee",
    pipe_glow="rgba(34,211,238,0.55)",
    zone_line="#2a3b5c",
    zone_label="#6f84a6",
    tooltip_bg="#0c1322",
    tooltip_border="#2c3a55",
)

LIGHT = Palette(
    dark=False,
    text="#0f2230",
    muted="#5b6b7a",
    faint="#5f6e7d",
    card="#ffffff",
    inset="#f6f9fb",
    border="#d5e0e8",
    grid="#e6edf2",
    accent="#0f7f6c",
    accent_soft="rgba(15,127,108,0.10)",
    critical="#c62f33",
    high="#d9620b",
    medium="#a88400",
    normal="#1f9d6e",
    warning="#b85a00",
    info="#2f6fe0",
    unknown="#8796a5",
    expected="#8796a5",
    map_bg="#ffffff",
    map_block="#e7eee9",
    map_block_edge="#e7eee9",
    map_river="#cde2f0",
    map_river_edge="#a8cbe3",
    pipe="#4aa58c",
    pipe_trunk="#2e8f78",
    pipe_glow="rgba(0,0,0,0)",
    zone_line="#b9c8d3",
    zone_label="#5b6b7a",
    tooltip_bg="#ffffff",
    tooltip_border="#d5e0e8",
)


def palette(dark: bool) -> Palette:
    return DARK if dark else LIGHT


def band_color(p: Palette, band: str) -> str:
    return {"critical": p.critical, "high": p.high, "medium": p.medium, "low": p.normal}.get(band, p.unknown)


def fill_color(p: Palette, status: str) -> str:
    return {"critical": p.critical, "warning": p.warning, "normal": p.normal}.get(status, p.unknown)


FONT = "Inter, system-ui, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, monospace"


def chart_base(p: Palette) -> dict:
    """Shared ECharts chrome: recessive hairline grid, text tokens, themed tooltip."""
    return {
        "backgroundColor": "transparent",
        "textStyle": {"fontFamily": FONT, "color": p.muted, "fontSize": 12},
        "animationDuration": 500,
        "animationDurationUpdate": 400,
        "tooltip": {
            "backgroundColor": p.tooltip_bg,
            "borderColor": p.tooltip_border,
            "borderWidth": 1,
            "padding": [8, 10],
            "textStyle": {"color": p.text, "fontFamily": FONT, "fontSize": 12},
            "extraCssText": "border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.18);",
        },
    }


def axis(p: Palette, **extra) -> dict:
    base = {
        "axisLine": {"lineStyle": {"color": p.border}},
        "axisTick": {"show": False},
        "axisLabel": {"color": p.muted, "fontSize": 11, "fontFamily": FONT},
        "splitLine": {"lineStyle": {"color": p.grid, "width": 1}},
        "nameTextStyle": {"color": p.muted, "fontSize": 11},
    }
    base.update(extra)
    return base
