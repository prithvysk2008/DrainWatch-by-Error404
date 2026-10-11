"""Drain Watch entry point. Run with: uv run app.py"""

from __future__ import annotations

import asyncio
import os
import secrets
from pathlib import Path

from fastapi import HTTPException
from nicegui import app, ui
from pydantic import BaseModel

from drainwatch import service
from drainwatch.models import ReportSource, ReportType, Severity

ROOT = Path(__file__).resolve().parent
app.add_static_files("/static", str(ROOT / "static"))

# Importing the page modules registers their routes.
from ui.pages import about, analytics, crew, incidents, login, map, overview, queue, sensors, wall, work_orders  # noqa: E402,F401

TICK_SECONDS = 0.25


async def _clock() -> None:
    """Advance the storm while it is playing. Pages pick up changes through service.version()."""
    while True:
        await asyncio.sleep(TICK_SECONDS)
        service.tick(TICK_SECONDS)


@app.on_startup
async def _startup() -> None:
    service.init()
    asyncio.create_task(_clock())


# ---------------------------------------------------------------- small JSON API


class ReportIn(BaseModel):
    drain_id: str
    type: ReportType
    severity: Severity
    reporter: str = "API"
    description: str = ""


@app.get("/api/drains")
def api_drains() -> list[dict]:
    """Current ranking. Simulated data."""
    return [
        {
            "rank": r.rank,
            "drain_id": r.info.id,
            "name": r.info.name,
            "zone": r.info.zone_name,
            "score": r.score.score,
            "band": r.score.band.value,
            "label": r.score.label.value,
            "confidence": r.score.confidence,
            "reason": r.score.explanation,
        }
        for r in service.drain_rows()
        if r.score
    ]


@app.get("/api/readings/{drain_id}")
def api_readings(drain_id: str) -> dict:
    detail = service.drain_detail(drain_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Unknown drain")
    return {"drain_id": drain_id, "times": detail.times, "observed_cm": detail.observed, "expected_cm": detail.expected}


@app.post("/api/reports", status_code=201)
def api_report(body: ReportIn) -> dict:
    if service.drain_info(body.drain_id) is None:
        raise HTTPException(status_code=404, detail="Unknown drain")
    report = service.log_report(
        body.drain_id,
        body.type,
        body.severity,
        ReportSource.citizen,
        body.reporter,
        body.description or "Submitted through the API.",
        actor="API",
    )
    score = service.score_for(body.drain_id)
    return {"report_id": report.id, "drain_id": body.drain_id, "new_score": score.score if score else None}


if os.environ.get("DRAINWATCH_DEV") == "1":

    @app.get("/__dev/advance")
    def dev_advance(steps: int = 1, scenario: str | None = None) -> dict:
        """Development only (DRAINWATCH_DEV=1): jump the storm forward for screenshots and testing."""
        if scenario:
            service.set_scenario(scenario, "dev")
        service.play("dev")
        for _ in range(steps):
            service.tick(1.0 / service.state().speed)
        service.pause("dev")
        return {"step": service.state().step}


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title="Drain Watch",
        favicon=str(ROOT / "static" / "icons" / "favicon.svg"),
        storage_secret=os.environ.get("DRAINWATCH_SECRET") or secrets.token_hex(16),
        port=int(os.environ.get("PORT", "8080")),
        reload=False,
        show=os.environ.get("DRAINWATCH_OPEN_BROWSER", "1") == "1",
        show_welcome_message=True,
    )
