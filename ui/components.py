"""Small reusable pieces: badges, KPI tiles, rings, meters, empty states."""

from __future__ import annotations

import html
import math
from datetime import datetime

from nicegui import ui

BAND_ICON = {"critical": "error", "high": "warning", "medium": "change_history", "low": "check_circle"}
BAND_TEXT = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}
FILL_ICON = {"critical": "error", "warning": "warning", "normal": "check_circle", "unknown": "help_outline"}
FILL_TEXT = {"critical": "Critical", "warning": "Warning", "normal": "Normal", "unknown": "No reading"}
FILL_TONE = {"critical": "critical", "warning": "warning", "normal": "normal", "unknown": "unknown"}
SEVERITY_TONE = {"critical": "critical", "high": "high", "medium": "medium"}
SEVERITY_TEXT = {"critical": "Critical: road flooded", "high": "High: rising fast", "medium": "Medium: stagnant"}
SEVERITY_SHORT = {"critical": "Critical", "high": "High", "medium": "Medium"}
REPORT_STATUS_TEXT = {"new": "New", "dispatched": "Crew dispatched", "resolved": "Resolved and cleared"}
REPORT_STATUS_TONE = {"new": "info", "dispatched": "warning", "resolved": "ok"}
LABEL_SHORT = {
    "Likely local blockage": "Local blockage",
    "Possible downstream congestion or widespread flooding": "Congestion or flooding",
    "Unverified report": "Unverified report",
    "Low confidence (no sensor)": "No sensor",
    "Low confidence (sensor fault)": "Sensor fault",
    "No anomaly": "No anomaly",
}
LABEL_ICON = {
    "Likely local blockage": "block",
    "Possible downstream congestion or widespread flooding": "waves",
    "Unverified report": "campaign",
    "Low confidence (no sensor)": "sensors_off",
    "Low confidence (sensor fault)": "sensors_off",
    "No anomaly": "done",
}


def button(*args, **kwargs) -> ui.button:
    """ui.button without Quasar colour classes. Quasar's colour utilities are !important inside a CSS layer,
    which would beat the design tokens, so colour comes only from the dw-btn-* classes."""
    kwargs.setdefault("color", None)
    return ui.button(*args, **kwargs).props("no-wrap")


def badge(text: str, tone: str, icon: str | None = None, solid: bool = False) -> ui.element:
    """Status is never colour alone: every badge carries text and, for states, an icon."""
    style = "is-solid" if solid else "is-soft"
    with ui.element("span").classes(f"dw-badge {style} tone-{tone}") as el:
        if icon:
            ui.icon(icon).props('aria-hidden="true"')
        ui.label(text)
    return el


def band_badge(band: str, score: float | None = None, solid: bool = False) -> ui.element:
    text = BAND_TEXT[band] if score is None else f"{BAND_TEXT[band]} {score:.0f}"
    return badge(text, band, BAND_ICON[band], solid)


def fill_badge(status: str, fill_pct: float | None = None) -> ui.element:
    text = FILL_TEXT[status] if fill_pct is None else f"{FILL_TEXT[status]} {fill_pct:.0f}%"
    return badge(text, FILL_TONE[status], FILL_ICON[status])


def label_badge(label: str) -> ui.element:
    return badge(label, "neutral", LABEL_ICON.get(label))


def severity_badge(severity: str) -> ui.element:
    icon = {"critical": "error", "high": "warning", "medium": "change_history"}[severity]
    return badge(SEVERITY_SHORT[severity], SEVERITY_TONE[severity], icon)


def kpi(
    label: str,
    value: int,
    *,
    tone: str | None = None,
    unit: str | None = None,
    note: str | None = None,
    count_up: bool = False,
) -> None:
    with ui.element("div").classes("dw-card dw-card-pad flex flex-col justify-between min-h-[104px]"):
        ui.label(label).classes("dw-kpi-label")
        with ui.row().classes("items-baseline gap-0 mt-1 no-wrap"):
            cls = "dw-kpi-value" + (f" is-{tone}" if tone else "")
            if count_up:
                ui.html(
                    f'<span class="{cls} dw-countup" style="--dw-to:{int(value)}" aria-label="{int(value)}"></span>',
                    sanitize=False,
                )
            else:
                ui.label(f"{value:,}").classes(cls)
            if unit:
                ui.label(unit).classes("dw-kpi-unit")
        if note:
            ui.label(note).classes("dw-kpi-note")


def ring(value: int, total: int, color_var: str, caption: str, size: int = 92) -> None:
    """A small SVG ring: value out of total, with the count in the centre and a caption below."""
    r = 38
    circumference = 2 * math.pi * r
    share = value / total if total else 0.0
    dash = f"{circumference * share:.1f} {circumference:.1f}"
    svg = (
        f'<svg class="dw-ring" width="{size}" height="{size}" viewBox="0 0 92 92" role="img" '
        f'aria-label="{html.escape(caption)}: {value} of {total}">'
        f'<circle class="ring-track" cx="46" cy="46" r="{r}" fill="none" stroke-width="8"/>'
        f'<circle class="ring-value" cx="46" cy="46" r="{r}" fill="none" stroke="var({color_var})" stroke-width="8" '
        f'stroke-linecap="round" stroke-dasharray="{dash}" transform="rotate(-90 46 46)"/>'
        f'<text x="46" y="53" text-anchor="middle" font-size="22">{value}</text></svg>'
    )
    with ui.column().classes("items-center gap-1"):
        ui.html(svg, sanitize=False)
        ui.label(caption).classes("dw-small dw-muted")


def meter(pct: float, color_var: str, label: str | None = None) -> None:
    pct = max(0.0, min(100.0, pct))
    with (
        ui.element("div")
        .classes("dw-meter w-full")
        .props(
            f'role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{pct:.0f}"'
            + (f' aria-label="{html.escape(label)}"' if label else "")
        )
    ):
        ui.element("div").style(f"width:{pct:.1f}%;background:var({color_var})")


def score_bar(score: float, band: str) -> None:
    with ui.element("div").classes("dw-scorebar"):
        with ui.element("div").classes("track"):
            ui.element("div").classes("fill").style(f"width:{score:.0f}%;background:var(--{_band_var(band)})")
        ui.label(f"{score:.0f}").classes("dw-mono dw-small font-semibold w-7 text-right")


def _band_var(band: str) -> str:
    return {"critical": "critical", "high": "high", "medium": "medium", "low": "normal"}[band]


def band_var(band: str) -> str:
    return f"--{_band_var(band)}"


def fill_var(status: str) -> str:
    return {"critical": "--critical", "warning": "--warning", "normal": "--normal"}.get(status, "--unknown")


def empty_state(text: str, icon: str = "inbox") -> None:
    with ui.element("div").classes("dw-empty flex flex-col items-center gap-2"):
        ui.icon(icon).classes("text-2xl dw-faint")
        ui.label(text)


def card_title(text: str, note: str | None = None) -> None:
    with ui.column().classes("gap-0"):
        ui.label(text).classes("dw-card-title")
        if note:
            ui.label(note).classes("dw-small dw-muted")


def ago(ts: datetime, now: datetime) -> str:
    minutes = int((now - ts).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours, rem = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {rem} min ago" if rem else f"{hours} h ago"
    return f"{hours // 24} days ago"


def minutes_text(minutes: float) -> str:
    sign = "-" if minutes < 0 else ""
    m = abs(int(round(minutes)))
    if m < 60:
        return f"{sign}{m} min"
    return f"{sign}{m // 60} h {m % 60:02d} min"
