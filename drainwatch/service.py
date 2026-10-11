"""The single data access layer. UI code calls these functions and nothing else in drainwatch.

State lives in two places:
  * SQLite (via db.py) for records: drains, reports, work orders, inspections, audit, settings.
  * The in-memory World for the running storm: simulated arrays, the clock and the current scores.
"""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sqlmodel import col, select

from drainwatch import analytics, auth, config, db, scoring
from drainwatch.allocation import CrewSlot, Job, Route, plan_routes, travel_minutes
from drainwatch.config import FillThresholds
from drainwatch.models import (
    AuditEvent,
    Band,
    Crew,
    Drain,
    DrainScore,
    FillStatus,
    Finding,
    GroundTruth,
    InspectionRecord,
    Label,
    Notification,
    RainObservation,
    Report,
    ReportSource,
    ReportStatus,
    ReportType,
    Role,
    Sensor,
    SensorDiagnostic,
    SensorReading,
    Setting,
    Severity,
    SimState,
    Stage,
    TruthKind,
    User,
    WorkOrder,
    Zone,
)
from drainwatch.network import neighbour_map
from drainwatch.simulate import (
    AVENUE_DX,
    AVENUE_X0,
    AVENUES,
    ROW_DY,
    ROW_STREETS,
    ROW_Y0,
    SCENARIOS,
    ZONE_SPLIT_X,
    ZONE_SPLIT_Y,
    ZONES,
    City,
    Faults,
    Run,
    SimReport,
    build_city,
    generate_history,
    generate_reports,
    plant_faults,
    scenario_start,
    simulate_run,
    step_time,
)

SPEEDS = (0.5, 1.0, 2.0, 4.0)  # steps per second
STAGE_LABELS = {
    Stage.pending: "Pending dispatch",
    Stage.en_route: "En route or site arrived",
    Stage.active: "Active jetting or de-clogging",
    Stage.resolved: "Resolved and verified",
}
CHECKLIST = ("Inspect inlet", "Clear debris", "Check outflow", "Photo before", "Photo after")
CREWS = (
    ("C1", "Jetting truck 1", "Jetting truck", 600.0, 2350.0),
    ("C2", "Jetting truck 2", "Jetting truck", 1250.0, 1000.0),
    ("C3", "Desilting crew A", "Desilting crew", 3150.0, 2300.0),
    ("C4", "Desilting crew B", "Desilting crew", 3300.0, 950.0),
    ("C5", "Structural unit", "Structural unit", 2200.0, 1650.0),
)
DEMO_USERS = (
    ("operator", Role.operator, "Duty operator", None),
    ("crew", Role.crew, "Crew lead, Jetting truck 2", "C2"),
)
TASK_FOR_LABEL = {
    Label.local_blockage: "Jet and clear the inlet",
    Label.congestion: "Inspect the trunk junction downstream",
    Label.unverified_report: "Verify the report on site",
}


@dataclass
class DrainInfo:
    """Static drain fields joined with zone name, cached for fast reads."""

    id: str
    name: str
    zone_id: str
    zone_name: str
    ward: str
    x: float
    y: float
    elevation: float
    max_depth_cm: float
    capacity_lps: float
    catchment_ha: float
    silt_prone: bool
    has_sensor: bool
    is_trunk: bool
    is_outfall: bool
    downstream_id: str | None
    critical_site: str | None
    site_name: str | None
    past_blockages: int
    last_inspected: datetime | None
    silt_pct: float


@dataclass
class World:
    city: City
    faults: Faults
    run: Run
    neighbours: dict[str, list[str]]
    drains: dict[str, DrainInfo]
    scenario: str
    start: datetime
    step: int = 0
    playing: bool = False
    speed: float = 1.0
    intensity_by_step: np.ndarray = field(default_factory=lambda: np.ones(config.SCENARIO_STEPS))
    thresholds: FillThresholds = field(default_factory=FillThresholds)
    scores: list[DrainScore] = field(default_factory=list)
    score_by_id: dict[str, DrainScore] = field(default_factory=dict)
    sim_reports: list[SimReport] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    accumulator: float = 0.0
    next_report: int = 1001
    next_order: int = 101
    finished: bool = False


_world: World | None = None
_version = 0  # module-level so it keeps rising across scenario resets


def world() -> World:
    if _world is None:
        init()
    assert _world is not None
    return _world


# ---------------------------------------------------------------- setup


def init(scenario: str = "Heavy storm", thresholds: FillThresholds | None = None) -> None:
    """Build the city and seed a fresh database. Called at startup and on reset."""
    global _world
    db.reset_db()
    city = build_city(config.SEED)
    faults = plant_faults(city, config.SEED)
    start = scenario_start(datetime.now())
    intensity = np.ones(config.SCENARIO_STEPS)
    run = simulate_run(city, faults, scenario, intensity)
    history = generate_history(city, start, config.SEED)
    zone_names = {z[0]: z[1] for z in ZONES}

    rng = np.random.default_rng(config.SEED + 5)
    past_blockages: dict[str, int] = {}
    last_inspected: dict[str, datetime] = {}
    for ev in history:
        if ev.finding != Finding.nothing.value:
            past_blockages[ev.drain_id] = past_blockages.get(ev.drain_id, 0) + 1
        last_inspected[ev.drain_id] = max(last_inspected.get(ev.drain_id, ev.resolved), ev.resolved)

    with db.session_scope() as s:
        for zid, name, importance in ZONES:
            s.add(Zone(id=zid, name=name, importance=importance))
        for cid, name, kind, bx, by in CREWS:
            s.add(Crew(id=cid, name=name, kind=kind, base_x=bx, base_y=by))
        s.flush()
        for d in sorted(city.drains, key=lambda d: d.is_outfall):  # outfalls last, after their upstream ids exist
            s.add(
                Drain(
                    id=d.id,
                    zone_id=d.zone_id,
                    ward=d.ward,
                    name=d.name,
                    x_m=d.x,
                    y_m=d.y,
                    elevation_m=d.elevation,
                    max_depth_cm=d.max_depth_cm,
                    capacity_lps=d.capacity_lps,
                    catchment_ha=d.catchment_ha,
                    silt_prone=d.silt_prone,
                    past_blockages=past_blockages.get(d.id, 0),
                    last_inspected=last_inspected.get(d.id),
                    has_sensor=d.has_sensor,
                    is_trunk=d.is_trunk,
                    is_outfall=d.is_outfall,
                    downstream_id=d.downstream_id,
                    critical_site=d.critical_site,
                    site_name=d.site_name,
                )
            )
        serial = 400
        for d in city.drains:
            if d.has_sensor:
                serial += int(rng.integers(1, 9))
                battery = int(rng.integers(12, 100)) if rng.random() < 0.12 else int(rng.integers(62, 100))
                signal = int(rng.integers(-108, -92)) if rng.random() < 0.08 else int(rng.integers(-88, -55))
                s.add(
                    Sensor(
                        serial=f"WL-{serial:04d}",
                        drain_id=d.id,
                        battery_pct=battery,
                        signal_dbm=signal,
                        calibration_offset_cm=round(float(rng.normal(0, 1.2)), 1),
                    )
                )
        for username, role, display, crew_id in DEMO_USERS:
            s.add(User(username=username, role=role, display_name=display, crew_id=crew_id))
        for k, ev in enumerate(history, start=1):
            d = next(x for x in city.drains if x.id == ev.drain_id)
            s.add(
                Report(
                    id=f"R-{k:04d}",
                    drain_id=ev.drain_id,
                    ts=ev.reported,
                    type=ev.type,
                    severity=ev.severity,
                    source=ReportSource.citizen,
                    reporter="Archive",
                    description="Simulated archive record.",
                    x_m=d.x,
                    y_m=d.y,
                    status=ReportStatus.resolved,
                    resolved_at=ev.resolved,
                    is_history=True,
                )
            )
            s.add(
                InspectionRecord(
                    drain_id=ev.drain_id,
                    ts=ev.resolved,
                    finding=Finding(ev.finding),
                    notes="Simulated archive record.",
                    is_history=True,
                )
            )
        for drain_id, onset in faults.blockages.items():
            s.add(GroundTruth(drain_id=drain_id, kind=TruthKind.local_blockage, onset_step=onset))
        for drain_id in sorted(faults.congestion_members):
            detail = "junction" if drain_id == faults.congestion_junction else "upstream of junction"
            s.add(
                GroundTruth(
                    drain_id=drain_id, kind=TruthKind.congestion, onset_step=faults.congestion_onset, detail=detail
                )
            )
        for drain_id, (kind, onset) in faults.faulty_sensors.items():
            s.add(GroundTruth(drain_id=drain_id, kind=TruthKind.faulty_sensor, onset_step=onset, detail=kind))
        th = thresholds or _load_thresholds(s)
        for key in ("unimpeded", "warning", "critical"):
            s.merge(Setting(key=f"threshold.{key}", value=str(getattr(th, key))))

    drains = {}
    for d in city.drains:
        days = (start - last_inspected[d.id]).days if d.id in last_inspected else 400
        silt = 8 + 30 * d.silt_prone + 22 * min(days, 365) / 365 + 5 * past_blockages.get(d.id, 0)
        drains[d.id] = DrainInfo(
            id=d.id,
            name=d.name,
            zone_id=d.zone_id,
            zone_name=zone_names[d.zone_id],
            ward=d.ward,
            x=d.x,
            y=d.y,
            elevation=d.elevation,
            max_depth_cm=d.max_depth_cm,
            capacity_lps=d.capacity_lps,
            catchment_ha=d.catchment_ha,
            silt_prone=d.silt_prone,
            has_sensor=d.has_sensor,
            is_trunk=d.is_trunk,
            is_outfall=d.is_outfall,
            downstream_id=d.downstream_id,
            critical_site=d.critical_site,
            site_name=d.site_name,
            past_blockages=past_blockages.get(d.id, 0),
            last_inspected=last_inspected.get(d.id),
            silt_pct=round(min(silt + float(rng.normal(0, 4)), 88.0), 0),
        )

    _world = World(
        city=city,
        faults=faults,
        run=run,
        neighbours=neighbour_map(city.graph, config.NEIGHBOUR_RADIUS_M),
        drains=drains,
        scenario=scenario,
        start=start,
        intensity_by_step=intensity,
        thresholds=th,
        sim_reports=generate_reports(city, faults, scenario, config.SEED),
    )
    _seed_routine_orders()
    _reveal_step(0)
    _rescore(notify=False)


def _load_thresholds(session) -> FillThresholds:
    rows = {r.key: float(r.value) for r in session.exec(select(Setting))}
    base = FillThresholds()
    return FillThresholds(
        unimpeded=rows.get("threshold.unimpeded", base.unimpeded),
        warning=rows.get("threshold.warning", base.warning),
        critical=rows.get("threshold.critical", base.critical),
    )


def _seed_routine_orders() -> None:
    """Two ordinary pre-storm jobs so the board is not empty before the storm starts."""
    w = _world
    assert w is not None
    silt_prone = sorted((d for d in w.drains.values() if d.silt_prone and not d.is_outfall), key=lambda d: d.id)
    morning = w.start.replace(hour=9, minute=40)
    with db.session_scope() as s:
        done, pending = silt_prone[0], silt_prone[1]
        s.add(
            WorkOrder(
                id=f"WO-{w.next_order}",
                drain_id=done.id,
                stage=Stage.resolved,
                crew_id="C3",
                task="Routine desilting before the storm",
                created=morning - timedelta(hours=2),
                due=morning,
                finding=Finding.silt,
                closed_at=morning,
                checklist_json=json.dumps(dict.fromkeys(CHECKLIST, True)),
            )
        )
        s.add(
            InspectionRecord(
                drain_id=done.id,
                ts=morning,
                finding=Finding.silt,
                crew_id="C3",
                notes="Routine desilting before the storm.",
            )
        )
        s.add(
            WorkOrder(
                id=f"WO-{w.next_order + 1}",
                drain_id=pending.id,
                stage=Stage.pending,
                task="Routine desilting before the storm",
                created=morning,
                due=w.start + timedelta(hours=4),
            )
        )
    w.drains[done.id].last_inspected = morning
    w.drains[done.id].silt_pct = 6
    w.next_order += 2


# ---------------------------------------------------------------- clock


def tick(dt: float) -> bool:
    """Advance the storm while playing. Returns True when the step changed."""
    w = world()
    if not w.playing:
        return False
    w.accumulator += dt * w.speed
    changed = False
    while w.accumulator >= 1.0 and w.playing:
        w.accumulator -= 1.0
        if w.step >= config.SCENARIO_STEPS - 1:
            w.playing = False
            w.finished = True
            _notify("Storm finished", f"{w.scenario} has ended. Rankings stay available for review.", "info")
            break
        w.step += 1
        _reveal_step(w.step)
        changed = True
    if changed:
        _rescore(notify=True)
    return changed


def state() -> SimState:
    w = world()
    return SimState(
        scenario=w.scenario,
        step=w.step,
        total_steps=config.SCENARIO_STEPS,
        playing=w.playing,
        speed=w.speed,
        intensity=float(w.intensity_by_step[min(w.step, config.SCENARIO_STEPS - 1)]),
        sim_time=now(),
    )


def version() -> int:
    return _version


def now() -> datetime:
    w = world()
    return step_time(w.start, w.step)


def scenarios() -> tuple[str, ...]:
    return SCENARIOS


def play(actor: str) -> None:
    w = world()
    if w.step >= config.SCENARIO_STEPS - 1:
        return
    w.playing = True
    w.finished = False
    _audit(actor, "Started storm playback", detail=w.scenario)
    _bump()


def pause(actor: str) -> None:
    w = world()
    w.playing = False
    _audit(actor, "Paused storm playback", detail=f"step {w.step}")
    _bump()


def set_speed(speed: float) -> None:
    world().speed = speed
    _bump()


def set_intensity(intensity: float, actor: str) -> None:
    """Scale rain from the current step onward. Past steps keep the rain that already fell."""
    w = world()
    w.intensity_by_step[w.step + 1 :] = intensity
    _resimulate()
    _audit(actor, "Changed storm intensity", detail=f"{intensity:.1f}x from step {w.step + 1}")
    _bump()


def set_scenario(scenario: str, actor: str) -> None:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    th = world().thresholds
    init(scenario, th)
    _audit(actor, "Loaded scenario", detail=scenario)
    _bump()


def reset(actor: str) -> None:
    set_scenario(world().scenario, actor)


def _resimulate() -> None:
    w = world()
    w.run = simulate_run(w.city, w.faults, w.scenario, w.intensity_by_step)
    _rescore(notify=False)


def _bump() -> None:
    global _version
    _version += 1


# ---------------------------------------------------------------- revealing data step by step


def _reveal_step(step: int) -> None:
    w = world()
    ts = step_time(w.start, step)
    with db.session_scope() as s:
        for k, (zid, _, _) in enumerate(ZONES):
            s.add(RainObservation(zone_id=zid, step=step, ts=ts, mm_per_10min=float(w.run.rain_zt[step, k])))
        for d in w.city.drains:
            if d.has_sensor:
                value = w.run.observed_cm[step, w.city.index[d.id]]
                s.add(SensorReading(drain_id=d.id, step=step, ts=ts, level_cm=None if math.isnan(value) else value))
    for r in (r for r in w.sim_reports if r.step == step):
        offset = (sum(map(ord, r.drain_id)) + step) % 9
        log_report(
            r.drain_id,
            r.type,
            r.severity,
            r.source,
            r.reporter,
            r.description,
            actor="Simulator",
            ts=ts - timedelta(minutes=offset),
            x_m=r.x,
            y_m=r.y,
            rescore=False,
        )


def _rescore(notify: bool) -> None:
    w = world()
    previous = {s.drain_id: s for s in w.scores}
    t = w.step
    now_ts = now()
    with db.session_scope() as s:
        active = s.exec(
            select(Report).where(Report.is_history == False, Report.status != ReportStatus.resolved)  # noqa: E712
        ).all()
    reports = [
        scoring.ReportInput(r.x_m, r.y_m, (now_ts - r.ts).total_seconds() / 60.0, r.severity)
        for r in active
        if r.duplicate_of is None
    ]
    importance = {z[0]: z[2] for z in ZONES}
    inputs = []
    for d in w.city.ranked:
        info = w.drains[d.id]
        i = w.city.index[d.id]
        zone_col = int(d.zone_id[1]) - 1
        recent_rain = float(w.run.rain_zt[max(0, t - 2) : t + 1, zone_col].mean())
        observed = w.run.observed_cm[: t + 1, i].tolist()
        expected = w.run.expected_cm[: t + 1, i].tolist()
        days = (now_ts - info.last_inspected).total_seconds() / 86400 if info.last_inspected else 400.0
        recently = bool(
            info.last_inspected and (now_ts - info.last_inspected).total_seconds() / 60 <= config.RECENT_INSPECTION_MIN
        )
        inputs.append(
            scoring.DrainInput(
                drain_id=d.id,
                x_m=d.x,
                y_m=d.y,
                zone_name=info.zone_name,
                max_depth_cm=d.max_depth_cm,
                has_sensor=d.has_sensor,
                sensor_state=scoring.diagnose_sensor(observed, expected) if d.has_sensor else SensorDiagnostic.no_data,
                observed_cm=observed,
                expected_cm=expected,
                spread_cm=w.run.spread_cm[: t + 1, i].tolist(),
                recent_rain_mm_10min=recent_rain,
                days_since_inspection=days,
                past_blockages=info.past_blockages,
                silt_prone=info.silt_prone,
                recently_inspected=recently,
                elevation_m=d.elevation,
                zone_importance=importance[d.zone_id],
                critical_site=bool(d.critical_site),
            )
        )
    w.scores = scoring.score_city(inputs, w.neighbours, reports, w.thresholds)
    w.score_by_id = {s.drain_id: s for s in w.scores}
    if notify:
        _notify_changes(previous)
    _bump()


def _notify_changes(previous: dict[str, DrainScore]) -> None:
    w = world()
    for sc in w.scores:
        before = previous.get(sc.drain_id)
        info = w.drains[sc.drain_id]
        if sc.band is Band.critical and (before is None or before.band is not Band.critical):
            _notify(
                f"{sc.drain_id} is now Critical",
                f"{info.name}. {sc.label.value}. Score {sc.score:.0f}.",
                "critical",
                sc.drain_id,
            )
            _audit("Scoring", "Priority rose to Critical", drain_id=sc.drain_id, detail=f"score {sc.score:.0f}")
        elif sc.band is Band.high and before is not None and before.band in (Band.medium, Band.low):
            _audit("Scoring", "Priority rose to High", drain_id=sc.drain_id, detail=f"score {sc.score:.0f}")
        elif before is not None and before.band is Band.critical and sc.band is not Band.critical:
            _audit(
                "Scoring",
                f"Priority fell to {sc.band.value.title()}",
                drain_id=sc.drain_id,
                detail=f"score {sc.score:.0f}",
            )
        if sc.fill_status is FillStatus.critical and (before is None or before.fill_status is not FillStatus.critical):
            _notify(
                f"{sc.drain_id} above critical level",
                f"{info.name} is {sc.fill_pct:.0f}% full.",
                "warning",
                sc.drain_id,
            )


def _notify(title: str, body: str, tone: str, drain_id: str | None = None) -> None:
    w = world()
    nid = (w.notifications[0].id + 1) if w.notifications else 1
    w.notifications.insert(0, Notification(id=nid, ts=now(), title=title, body=body, tone=tone, drain_id=drain_id))
    del w.notifications[60:]


def _audit(actor: str, action: str, drain_id: str | None = None, order_id: str | None = None, detail: str = "") -> None:
    with db.session_scope() as s:
        s.add(
            AuditEvent(ts=now(), actor=actor, action=action, drain_id=drain_id, work_order_id=order_id, detail=detail)
        )


# ---------------------------------------------------------------- read models for the UI


@dataclass
class DrainRow:
    info: DrainInfo
    score: DrainScore | None
    rank: int | None
    report_count: int
    open_order: WorkOrder | None


def zones() -> list[tuple[str, str]]:
    return [(z[0], z[1]) for z in ZONES]


def thresholds() -> FillThresholds:
    return world().thresholds


def drain_info(drain_id: str) -> DrainInfo | None:
    return world().drains.get(drain_id)


def score_for(drain_id: str) -> DrainScore | None:
    return world().score_by_id.get(drain_id)


def network_edges() -> list[tuple[DrainInfo, DrainInfo]]:
    w = world()
    return [(w.drains[a], w.drains[b]) for a, b in w.city.graph.edges]


def _open_orders() -> dict[str, WorkOrder]:
    with db.session_scope() as s:
        rows = s.exec(select(WorkOrder).where(WorkOrder.stage != Stage.resolved)).all()
    return {o.drain_id: o for o in sorted(rows, key=lambda o: o.created)}


def _live_report_counts() -> dict[str, int]:
    with db.session_scope() as s:
        rows = s.exec(
            select(Report.drain_id).where(
                Report.is_history == False,  # noqa: E712
                Report.status != ReportStatus.resolved,
            )
        ).all()
    out: dict[str, int] = {}
    for drain_id in rows:
        out[drain_id] = out.get(drain_id, 0) + 1
    return out


def drain_rows(zone_id: str | None = None) -> list[DrainRow]:
    """Ranked drains (highest priority first), optionally limited to one zone."""
    w = world()
    orders = _open_orders()
    counts = _live_report_counts()
    rows = []
    for rank, sc in enumerate(w.scores, start=1):
        info = w.drains[sc.drain_id]
        if zone_id and info.zone_id != zone_id:
            continue
        rows.append(DrainRow(info, sc, rank, counts.get(sc.drain_id, 0), orders.get(sc.drain_id)))
    return rows


def outfalls() -> list[DrainInfo]:
    return [d for d in world().drains.values() if d.is_outfall]


def search(query: str, limit: int = 8) -> list[DrainInfo]:
    q = query.strip().lower()
    if not q:
        return []
    w = world()
    hits = [
        d
        for d in w.drains.values()
        if not d.is_outfall and (q in d.id.lower() or q in d.name.lower() or q in d.ward.lower())
    ]
    hits.sort(key=lambda d: (not d.id.lower().startswith(q), d.id))
    return hits[:limit]


def city_rain_mm_h() -> float:
    w = world()
    return float(w.run.city_rain[w.step]) * 6.0


def threat() -> tuple[int, str]:
    w = world()
    rate = city_rain_mm_h()
    ranked = [s for s in w.scores if s.fill_status is not FillStatus.unknown]
    share = sum(1 for s in ranked if s.fill_status in (FillStatus.warning, FillStatus.critical)) / max(len(ranked), 1)
    current = config.THREAT_LEVELS[0]
    for lvl in config.THREAT_LEVELS:
        if rate >= lvl.min_rain_mm_h or share >= lvl.min_share_above_warning:
            current = lvl
    return current.level, current.name


def kpis(zone_id: str | None = None) -> dict[str, int]:
    w = world()
    scores = [s for s in w.scores if not zone_id or w.drains[s.drain_id].zone_id == zone_id]
    shift_start = w.start
    with db.session_scope() as s:
        inspections = s.exec(
            select(InspectionRecord).where(
                InspectionRecord.is_history == False,  # noqa: E712
                InspectionRecord.ts >= shift_start,
            )
        ).all()
    if zone_id:
        inspections = [i for i in inspections if w.drains[i.drain_id].zone_id == zone_id]
    return {
        "monitored": len(scores),
        "critical": sum(1 for s in scores if s.band is Band.critical),
        "likely_blocked": sum(1 for s in scores if s.label is Label.local_blockage),
        "inspections": len(inspections),
        "target": config.INSPECTIONS_TARGET_PER_SHIFT,
        "above_warning": sum(1 for s in scores if s.fill_status in (FillStatus.warning, FillStatus.critical)),
    }


def storm_banner() -> tuple[str, str] | None:
    """(tone, sentence) while a storm is running or has rain, else None."""
    w = world()
    if w.step == 0 and not w.playing:
        return None
    k = kpis()
    end = step_time(w.start, config.SCENARIO_STEPS - 1) + timedelta(minutes=config.STEP_MINUTES)
    level, name = threat()
    if w.finished:
        return "info", (
            f"{w.scenario} has finished. {k['above_warning']} drains are still above warning level and "
            f"{k['critical']} still need inspection."
        )
    tone = {1: "info", 2: "advisory", 3: "warning", 4: "critical"}[level]
    lead = "Storm watch active" if level < 4 else "Flash flood warning in force"
    return tone, (
        f"{lead} until {end:%H:%M}. {k['above_warning']} drains are above warning level and "
        f"{k['critical']} need inspection now."
    )


def fill_summary(zone_id: str | None = None) -> dict[str, float]:
    w = world()
    scores = [s for s in w.scores if not zone_id or w.drains[s.drain_id].zone_id == zone_id]
    fills = [s.fill_pct for s in scores if s.fill_pct is not None and s.sensor_ok]
    return {
        "average": round(sum(fills) / len(fills), 0) if fills else 0.0,
        "normal": sum(1 for s in scores if s.fill_status is FillStatus.normal),
        "warning": sum(1 for s in scores if s.fill_status is FillStatus.warning),
        "critical": sum(1 for s in scores if s.fill_status is FillStatus.critical),
        "unknown": sum(1 for s in scores if s.fill_status is FillStatus.unknown),
    }


def crews() -> list[Crew]:
    with db.session_scope() as s:
        return list(s.exec(select(Crew).order_by(Crew.id)).all())


def crews_available() -> list[Crew]:
    """Crews not currently travelling to or working at a job."""
    busy = {o.crew_id for o in _open_orders().values() if o.stage in (Stage.en_route, Stage.active)}
    return [c for c in crews() if c.id not in busy]


def crews_free() -> tuple[int, int]:
    all_crews = crews()
    busy = {o.crew_id for o in _open_orders().values() if o.stage in (Stage.en_route, Stage.active)}
    return sum(1 for c in all_crews if c.id not in busy), len(all_crews)


def rainfall_series() -> list[tuple[str, float, bool]]:
    """City rainfall in mm per 10 minutes for the whole scenario. The flag marks steps not yet reached."""
    w = world()
    return [
        (f"{step_time(w.start, k):%H:%M}", float(w.run.city_rain[k]), k > w.step) for k in range(config.SCENARIO_STEPS)
    ]


def watch_points() -> list[tuple[DrainInfo, DrainScore | None]]:
    """Flood-prone points: drains serving critical sites, plus the lowest drain on Canal Street."""
    w = world()
    sites = [d for d in w.drains.values() if d.site_name and d.critical_site in ("underpass", "market", "hospital")]
    canal = min(
        (d for d in w.drains.values() if d.name.startswith("Canal Street") and d.has_sensor),
        key=lambda d: d.elevation,
        default=None,
    )
    points = ([canal] if canal else []) + sorted(sites, key=lambda d: d.id)
    return [(d, w.score_by_id.get(d.id)) for d in points]


def sensor_health(zone_id: str | None = None) -> dict[str, int]:
    w = world()
    scores = [
        s
        for s in w.scores
        if w.drains[s.drain_id].has_sensor and (not zone_id or w.drains[s.drain_id].zone_id == zone_id)
    ]
    return {
        "total": len(scores),
        "normal": sum(1 for s in scores if s.fill_status is FillStatus.normal),
        "warning": sum(1 for s in scores if s.fill_status is FillStatus.warning),
        "alarm": sum(1 for s in scores if s.fill_status is FillStatus.critical),
        "faulty": sum(1 for s in scores if not s.sensor_ok),
        "rain_gauges": len(ZONES),
    }


def notifications() -> list[Notification]:
    return list(world().notifications)


# ---------------------------------------------------------------- drain detail


@dataclass
class DrainDetail:
    info: DrainInfo
    score: DrainScore | None
    rank: int | None
    times: list[str]
    observed: list[float | None]
    expected: list[float]
    spread: list[float]
    rain_mm_10min: list[float]
    velocity_ms: float
    reports: list[Report]
    inspections: list[InspectionRecord]
    orders: list[WorkOrder]
    audit: list[AuditEvent]
    sensor: Sensor | None
    neighbours_high: list[str]


def drain_detail(drain_id: str) -> DrainDetail | None:
    w = world()
    info = w.drains.get(drain_id)
    if info is None:
        return None
    i = w.city.index[drain_id]
    t = w.step
    zone_col = int(info.zone_id[1]) - 1
    obs = w.run.observed_cm[: t + 1, i]
    with db.session_scope() as s:
        near = s.exec(select(Report).where(Report.is_history == False).order_by(col(Report.ts).desc())).all()  # noqa: E712
        reports = [
            r
            for r in near
            if math.hypot(r.x_m - info.x, r.y_m - info.y) <= config.REPORT_RADIUS_M or r.drain_id == drain_id
        ]
        inspections = s.exec(
            select(InspectionRecord)
            .where(InspectionRecord.drain_id == drain_id)
            .order_by(col(InspectionRecord.ts).desc())
        ).all()
        orders = s.exec(
            select(WorkOrder).where(WorkOrder.drain_id == drain_id).order_by(col(WorkOrder.created).desc())
        ).all()
        audit = s.exec(
            select(AuditEvent).where(AuditEvent.drain_id == drain_id).order_by(col(AuditEvent.id).desc())
        ).all()
        sensor = s.exec(select(Sensor).where(Sensor.drain_id == drain_id)).first()
    rank = next((k for k, sc in enumerate(w.scores, start=1) if sc.drain_id == drain_id), None)
    high = []
    for n in w.neighbours.get(drain_id, []):
        sc = w.score_by_id.get(n)
        if sc and sc.sensor_ok and sc.signals.anomaly >= 0.5:
            high.append(n)
    return DrainDetail(
        info=info,
        score=w.score_by_id.get(drain_id),
        rank=rank,
        times=[f"{step_time(w.start, k):%H:%M}" for k in range(t + 1)],
        observed=[None if math.isnan(v) else round(float(v), 1) for v in obs],
        expected=[round(float(v), 1) for v in w.run.expected_cm[: t + 1, i]],
        spread=[round(float(v), 1) for v in w.run.spread_cm[: t + 1, i]],
        rain_mm_10min=[round(float(v), 2) for v in w.run.rain_zt[: t + 1, zone_col]],
        velocity_ms=float(w.run.velocity_ms[t, i]),
        reports=list(reports),
        inspections=list(inspections),
        orders=list(orders),
        audit=list(audit),
        sensor=sensor,
        neighbours_high=high,
    )


# ---------------------------------------------------------------- reports and incidents


def _report_id() -> str:
    w = world()
    rid = f"R-{w.next_report}"
    w.next_report += 1
    return rid


def log_report(
    drain_id: str,
    type: ReportType,
    severity: Severity,
    source: ReportSource,
    reporter: str,
    description: str,
    actor: str,
    ts: datetime | None = None,
    x_m: float | None = None,
    y_m: float | None = None,
    photo_path: str | None = None,
    rescore: bool = True,
) -> Report:
    """Add a report. A report on the same drain within the last hour is marked as a possible duplicate."""
    w = world()
    info = w.drains[drain_id]
    ts = ts or now()
    with db.session_scope() as s:
        earlier = s.exec(
            select(Report).where(
                Report.drain_id == drain_id,
                Report.is_history == False,  # noqa: E712
                Report.status != ReportStatus.resolved,
                col(Report.duplicate_of).is_(None),
            )
        ).all()
        duplicate = next((r.id for r in earlier if timedelta(0) <= ts - r.ts <= timedelta(hours=1)), None)
        report = Report(
            id=_report_id(),
            drain_id=drain_id,
            ts=ts,
            type=type,
            severity=severity,
            source=source,
            reporter=reporter.strip() or source.value,
            description=description.strip(),
            x_m=info.x if x_m is None else x_m,
            y_m=info.y if y_m is None else y_m,
            photo_path=photo_path,
            duplicate_of=duplicate,
        )
        if drain_id in _open_orders():
            report.status = ReportStatus.dispatched
        s.add(report)
    _audit(actor, "Report logged", drain_id=drain_id, detail=f"{report.id}: {type.value}, {severity.value}")
    tone = "critical" if severity is Severity.critical else "warning"
    _notify(f"New report {report.id}", f"{type.value} at {info.name}.", tone, drain_id)
    if rescore:
        _rescore(notify=True)
    return report


@dataclass
class IncidentRow:
    report: Report
    drain: DrainInfo
    crew_name: str | None


def incidents(status: str | None = None, type: str | None = None, severity: str | None = None) -> list[IncidentRow]:
    w = world()
    orders = _open_orders()
    crew_names = {c.id: c.name for c in crews()}
    with db.session_scope() as s:
        rows = s.exec(select(Report).where(Report.is_history == False).order_by(col(Report.ts).desc())).all()  # noqa: E712
    out = []
    for r in rows:
        if status and r.status.value != status:
            continue
        if type and r.type.value != type:
            continue
        if severity and r.severity.value != severity:
            continue
        order = orders.get(r.drain_id)
        out.append(
            IncidentRow(r, w.drains[r.drain_id], crew_names.get(order.crew_id) if order and order.crew_id else None)
        )
    return out


def open_incident_count() -> int:
    with db.session_scope() as s:
        return len(
            s.exec(
                select(Report.id).where(
                    Report.is_history == False,  # noqa: E712
                    Report.status == ReportStatus.new,
                )
            ).all()
        )


def mark_false_alarm(drain_id: str, actor: str) -> int:
    """Close open reports on the drain and reset a faulty sensor. Returns the number of reports closed."""
    w = world()
    closed = 0
    with db.session_scope() as s:
        for r in s.exec(
            select(Report).where(
                Report.drain_id == drain_id,
                Report.is_history == False,  # noqa: E712
                Report.status != ReportStatus.resolved,
            )
        ).all():
            r.status = ReportStatus.resolved
            r.resolved_at = now()
            s.add(r)
            closed += 1
    if drain_id in w.faults.faulty_sensors and drain_id not in w.faults.sensor_reset:
        w.faults.sensor_reset[drain_id] = w.step + 1
        _resimulate()
    _audit(
        actor,
        "Marked false alarm and reset sensor",
        drain_id=drain_id,
        detail=f"{closed} report{'s' if closed != 1 else ''} closed",
    )
    _rescore(notify=False)
    return closed


# ---------------------------------------------------------------- work orders


@dataclass
class OrderRow:
    order: WorkOrder
    drain: DrainInfo
    score: DrainScore | None
    crew_name: str | None
    sla_min: float  # minutes left in simulated time, negative when overdue
    eta_min: float | None


def _order_id() -> str:
    w = world()
    oid = f"WO-{w.next_order}"
    w.next_order += 1
    return oid


def _eta(order: WorkOrder, crew_by_id: dict[str, Crew]) -> float | None:
    if not order.crew_id or order.stage is Stage.resolved:
        return None
    crew = crew_by_id[order.crew_id]
    info = world().drains[order.drain_id]
    return round(travel_minutes((crew.base_x, crew.base_y), (info.x, info.y)) + 5)


def order_rows(crew_id: str | None = None) -> list[OrderRow]:
    w = world()
    crew_by_id = {c.id: c for c in crews()}
    with db.session_scope() as s:
        query = select(WorkOrder)
        if crew_id:
            query = query.where(WorkOrder.crew_id == crew_id)
        orders = s.exec(query).all()
    now_ts = now()
    rows = []
    for o in orders:
        sla = (o.due - now_ts).total_seconds() / 60.0
        rows.append(
            OrderRow(
                o,
                w.drains[o.drain_id],
                w.score_by_id.get(o.drain_id),
                crew_by_id[o.crew_id].name if o.crew_id else None,
                sla,
                _eta(o, crew_by_id),
            )
        )
    rows.sort(
        key=lambda r: (
            r.order.route_order if r.order.route_order is not None else 99,
            -(r.score.score if r.score else 0),
            r.order.id,
        )
    )
    return rows


def _task_for(drain_id: str) -> str:
    sc = world().score_by_id.get(drain_id)
    if sc and sc.label in TASK_FOR_LABEL:
        return TASK_FOR_LABEL[sc.label]
    return "Inspect and clear"


def create_order(drain_id: str, actor: str, crew_id: str | None = None) -> WorkOrder:
    """Open a work order for the drain, or return the one already open."""
    existing = _open_orders().get(drain_id)
    if existing:
        return existing
    w = world()
    sc = w.score_by_id.get(drain_id)
    band = sc.band.value if sc else "low"
    created = now()
    order = WorkOrder(
        id=_order_id(),
        drain_id=drain_id,
        stage=Stage.en_route if crew_id else Stage.pending,
        crew_id=crew_id,
        task=_task_for(drain_id),
        created=created,
        due=created + timedelta(minutes=config.SLA_MINUTES[band]),
        checklist_json=json.dumps(dict.fromkeys(CHECKLIST, False)),
    )
    with db.session_scope() as s:
        s.add(order)
        for r in s.exec(select(Report).where(Report.drain_id == drain_id, Report.status == ReportStatus.new)).all():
            r.status = ReportStatus.dispatched
            s.add(r)
    _audit(
        actor,
        "Work order created",
        drain_id=drain_id,
        order_id=order.id,
        detail=f"{order.task}" + (f", crew {crew_id}" if crew_id else ""),
    )
    _bump()
    return order


def nearest_free_crew(drain_id: str) -> Crew | None:
    info = world().drains[drain_id]
    busy = {o.crew_id for o in _open_orders().values() if o.stage in (Stage.en_route, Stage.active)}
    free = [c for c in crews() if c.id not in busy]
    if not free:
        return None
    return min(free, key=lambda c: (math.hypot(c.base_x - info.x, c.base_y - info.y), c.id))


def dispatch(drain_id: str, actor: str) -> tuple[WorkOrder, Crew | None]:
    """Create or reuse an order and send the nearest free crew. With no free crew, the order waits."""
    order = create_order(drain_id, actor)
    if order.crew_id:
        return order, next((c for c in crews() if c.id == order.crew_id), None)
    crew = nearest_free_crew(drain_id)
    if crew:
        assign_order(order.id, crew.id, actor)
        order.crew_id = crew.id
    return order, crew


def assign_order(order_id: str, crew_id: str, actor: str, route_order: int | None = None, start: bool = True) -> None:
    with db.session_scope() as s:
        order = s.get(WorkOrder, order_id)
        if order is None or order.stage is Stage.resolved:
            return
        order.crew_id = crew_id
        order.route_order = route_order
        if start and order.stage is Stage.pending:
            order.stage = Stage.en_route
        s.add(order)
        drain_id = order.drain_id
    _audit(actor, "Crew assigned", drain_id=drain_id, order_id=order_id, detail=crew_id)
    _bump()


def move_order(order_id: str, stage: Stage, actor: str, finding: Finding | None = None) -> None:
    """Move an order between board columns. Resolving records an inspection and clears the drain."""
    world()
    with db.session_scope() as s:
        order = s.get(WorkOrder, order_id)
        if order is None or order.stage is stage:
            return
        previous = order.stage
        order.stage = stage
        if stage is Stage.resolved:
            order.closed_at = now()
            order.finding = finding or order.finding or Finding.nothing
        elif previous is Stage.resolved:
            order.closed_at = None
        s.add(order)
        drain_id, crew_id, result = order.drain_id, order.crew_id, order.finding
    _audit(actor, f"Work order moved to {STAGE_LABELS[stage].lower()}", drain_id=drain_id, order_id=order_id)
    if stage is Stage.resolved:
        _record_clearance(drain_id, crew_id, result or Finding.nothing, actor)
        _advance_route(crew_id, actor)
    _bump()
    if stage is Stage.resolved:
        _rescore(notify=False)


def _record_clearance(drain_id: str, crew_id: str | None, finding: Finding, actor: str) -> None:
    w = world()
    ts = now()
    with db.session_scope() as s:
        s.add(InspectionRecord(drain_id=drain_id, ts=ts, finding=finding, crew_id=crew_id))
        drain = s.get(Drain, drain_id)
        if drain:
            drain.last_inspected = ts
            if finding is not Finding.nothing:
                drain.past_blockages += 1
            s.add(drain)
        for r in s.exec(
            select(Report).where(
                Report.drain_id == drain_id,
                Report.is_history == False,  # noqa: E712
                Report.status != ReportStatus.resolved,
            )
        ).all():
            r.status = ReportStatus.resolved
            r.resolved_at = ts
            s.add(r)
    info = w.drains[drain_id]
    info.last_inspected = ts
    info.silt_pct = 5
    if finding is not Finding.nothing:
        info.past_blockages += 1
    # Clearing restores flow from the next step if the simulation had a blockage here.
    if drain_id in w.faults.blockages or drain_id == w.faults.congestion_junction:
        w.faults.cleared.setdefault(drain_id, w.step + 1)
        _resimulate()
    _notify(f"{drain_id} cleared", f"{info.name}. Finding: {finding.value}.", "ok", drain_id)
    _audit(actor, "Inspection recorded", drain_id=drain_id, detail=finding.value)


def _advance_route(crew_id: str | None, actor: str) -> None:
    """When a crew finishes a job, its next queued stop becomes en route."""
    if not crew_id:
        return
    with db.session_scope() as s:
        queued = s.exec(
            select(WorkOrder)
            .where(WorkOrder.crew_id == crew_id, WorkOrder.stage == Stage.pending)
            .order_by(col(WorkOrder.route_order))
        ).all()
        busy = s.exec(
            select(WorkOrder).where(
                WorkOrder.crew_id == crew_id, col(WorkOrder.stage).in_([Stage.en_route, Stage.active])
            )
        ).first()
        if queued and not busy:
            nxt = queued[0]
            nxt.stage = Stage.en_route
            s.add(nxt)
            _audit(actor, "Next stop started", drain_id=nxt.drain_id, order_id=nxt.id, detail=crew_id)


def update_order(
    order_id: str,
    *,
    notes: str | None = None,
    checklist: dict[str, bool] | None = None,
    finding: Finding | None = None,
    photo_before: str | None = None,
    photo_after: str | None = None,
) -> None:
    with db.session_scope() as s:
        order = s.get(WorkOrder, order_id)
        if order is None:
            return
        if notes is not None:
            order.notes = notes
        if checklist is not None:
            order.checklist_json = json.dumps(checklist)
        if finding is not None:
            order.finding = finding
        if photo_before is not None:
            order.photo_before = photo_before
        if photo_after is not None:
            order.photo_after = photo_after
        s.add(order)
    _bump()


def order(order_id: str) -> WorkOrder | None:
    with db.session_scope() as s:
        return s.get(WorkOrder, order_id)


# ---------------------------------------------------------------- crew planner


@dataclass
class PlanPreview:
    routes: list[Route]
    leftover: list[Job]
    new_drains: list[str]  # drains that will get a new work order


def preview_plan(n_crews: int, per_crew: int, include_ranked: bool) -> PlanPreview:
    """Plan routes for pending orders, plus Critical and High drains that have no order yet."""
    w = world()
    open_orders = _open_orders()
    jobs = []
    for o in open_orders.values():
        if o.stage is Stage.pending:
            info = w.drains[o.drain_id]
            sc = w.score_by_id.get(o.drain_id)
            jobs.append(Job(o.id, o.drain_id, info.x, info.y, sc.score if sc else 0.0))
    new_drains = []
    if include_ranked:
        for sc in w.scores:
            if sc.band in (Band.critical, Band.high) and sc.drain_id not in open_orders:
                info = w.drains[sc.drain_id]
                jobs.append(Job(sc.drain_id, sc.drain_id, info.x, info.y, sc.score))
                new_drains.append(sc.drain_id)
    busy = {o.crew_id for o in open_orders.values() if o.stage in (Stage.en_route, Stage.active)}
    free = [c for c in crews() if c.id not in busy][:n_crews]
    slots = [CrewSlot(c.id, c.base_x, c.base_y, per_crew) for c in free]
    routes, leftover = plan_routes(jobs, slots)
    planned = {j.drain_id for r in routes for j in r.stops}
    return PlanPreview(routes, leftover, [d for d in new_drains if d in planned])


def apply_plan(plan: PlanPreview, actor: str) -> int:
    count = 0
    for route in plan.routes:
        for position, job in enumerate(route.stops, start=1):
            order_id = job.key if job.key.startswith("WO-") else create_order(job.drain_id, actor).id
            assign_order(order_id, route.crew_id, actor, route_order=position, start=position == 1)
            count += 1
    _audit(actor, "Applied crew plan", detail=f"{count} stops across {len(plan.routes)} crews")
    _bump()
    return count


# ---------------------------------------------------------------- sensors and thresholds


@dataclass
class SensorRow:
    sensor: Sensor
    drain: DrainInfo
    last_ping_min: int | None
    diagnostic: SensorDiagnostic


def sensor_rows() -> list[SensorRow]:
    w = world()
    with db.session_scope() as s:
        sensors = s.exec(select(Sensor).order_by(Sensor.serial)).all()
    rows = []
    for sensor in sensors:
        i = w.city.index[sensor.drain_id]
        obs = w.run.observed_cm[: w.step + 1, i]
        valid = np.where(~np.isnan(obs))[0]
        last_ping = None if len(valid) == 0 else int((w.step - valid[-1]) * config.STEP_MINUTES)
        diag = scoring.diagnose_sensor(obs.tolist(), w.run.expected_cm[: w.step + 1, i].tolist())
        if diag is SensorDiagnostic.optimal:
            if sensor.battery_pct < 20:
                diag = SensorDiagnostic.low_battery
            elif sensor.signal_dbm < -95:
                diag = SensorDiagnostic.weak_signal
        rows.append(SensorRow(sensor, w.drains[sensor.drain_id], last_ping, diag))
    return rows


def save_thresholds(unimpeded: float, warning: float, critical: float, actor: str) -> None:
    if not unimpeded < warning < critical <= 100:
        raise ValueError("Thresholds must rise: unimpeded below warning, warning below critical.")
    w = world()
    w.thresholds = FillThresholds(unimpeded=unimpeded, warning=warning, critical=critical)
    with db.session_scope() as s:
        for key in ("unimpeded", "warning", "critical"):
            s.merge(Setting(key=f"threshold.{key}", value=str(getattr(w.thresholds, key))))
    _audit(actor, "Saved calibration profile", detail=f"{unimpeded:.0f} / {warning:.0f} / {critical:.0f} percent")
    _rescore(notify=False)


# ---------------------------------------------------------------- analytics and validation


WINDOWS = ("Current monsoon season", "Pre-monsoon de-silt drive", "Past 12 months")


def _window_bounds(window: str) -> tuple[datetime, datetime]:
    end = now()
    year = end.year if end.month >= 6 else end.year - 1
    if window == "Current monsoon season":
        return datetime(year, 6, 1), end
    if window == "Pre-monsoon de-silt drive":
        return datetime(year, 4, 1), datetime(year, 6, 1)
    return end - timedelta(days=365), end


def analytics_data(window: str, zone_id: str | None = None) -> dict:
    w = world()
    lo, hi = _window_bounds(window)
    with db.session_scope() as s:
        reports = s.exec(select(Report).where(Report.ts >= lo, Report.ts <= hi)).all()
        inspections = s.exec(select(InspectionRecord).where(InspectionRecord.ts >= lo, InspectionRecord.ts <= hi)).all()
    if zone_id:
        reports = [r for r in reports if w.drains[r.drain_id].zone_id == zone_id]
        inspections = [i for i in inspections if w.drains[i.drain_id].zone_id == zone_id]
    t = w.step
    sensor_cols = [w.city.index[d.id] for d in w.city.ranked if d.has_sensor and (not zone_id or d.zone_id == zone_id)]
    depth = np.array([w.city.drains[i].max_depth_cm for i in sensor_cols])
    obs = w.run.observed_cm[: t + 1][:, sensor_cols]
    with np.errstate(invalid="ignore"):
        avg_fill = np.nanmean(obs / depth * 100, axis=1) if len(sensor_cols) else np.zeros(t + 1)
    exp_fill = (
        (w.run.expected_cm[: t + 1][:, sensor_cols] / depth * 100).mean(axis=1) if len(sensor_cols) else np.zeros(t + 1)
    )
    rain_mm_h = (w.run.city_rain[: t + 1] * 6).tolist()
    resolved = [(w.drains[r.drain_id].zone_name, r.ts, r.resolved_at) for r in reports if r.resolved_at]
    return {
        "times": [f"{step_time(w.start, k):%H:%M}" for k in range(t + 1)],
        "rain_mm_h": [round(v, 1) for v in rain_mm_h],
        "avg_fill": [round(float(v), 1) for v in avg_fill],
        "expected_fill": [round(float(v), 1) for v in exp_fill],
        "lag_min": analytics.response_lag_minutes(rain_mm_h, avg_fill.tolist()),
        "hotspots": analytics.counts(w.drains[r.drain_id].ward for r in reports)[:8],
        "causes": analytics.counts(i.finding.value for i in inspections if i.finding is not Finding.nothing),
        "mttr": analytics.mean_minutes_by(resolved),
        "n_reports": len(reports),
        "n_inspections": len(inspections),
        "window": (lo, hi),
    }


def validation() -> dict:
    """Compare the ranking with the hidden simulation truth. Only this function reads GroundTruth."""
    w = world()
    t = w.step
    with db.session_scope() as s:
        truth_rows = s.exec(select(GroundTruth).where(GroundTruth.kind != TruthKind.faulty_sensor)).all()
    truth = set()
    for row in truth_rows:
        cleared_at = w.faults.cleared.get(
            row.drain_id if row.kind is TruthKind.local_blockage else w.faults.congestion_junction
        )
        if row.onset_step <= t and (cleared_at is None or cleared_at > t):
            truth.add(row.drain_id)
    ranked = [s.drain_id for s in w.scores]
    p10 = scoring.precision_at_k(ranked, truth, 10)
    r20 = scoring.recall_at_k(ranked, truth, 20)
    base_p10, _ = scoring.random_baseline(len(ranked), len(truth), 10)
    _, base_r20 = scoring.random_baseline(len(ranked), len(truth), 20)
    return {
        "truth_count": len(truth),
        "precision_at_10": p10,
        "recall_at_20": r20,
        "random_precision_at_10": base_p10,
        "random_recall_at_20": base_r20,
        "step": t,
    }


def impact() -> dict[str, float | int | None]:
    with db.session_scope() as s:
        orders = s.exec(select(WorkOrder).where(WorkOrder.created >= world().start)).all()
        closed_reports = s.exec(
            select(Report).where(
                Report.is_history == False,  # noqa: E712
                Report.status == ReportStatus.resolved,
            )
        ).all()
    done = [o for o in orders if o.stage is Stage.resolved and o.closed_at]
    minutes = sorted((o.closed_at - o.created).total_seconds() / 60 for o in done if o.closed_at)
    median = minutes[len(minutes) // 2] if minutes else None
    return {
        "orders_opened": len(orders),
        "orders_resolved": len(done),
        "reports_closed": len(closed_reports),
        "median_minutes": median,
    }


# ---------------------------------------------------------------- export


def dispatch_batch_csv(limit: int = 20) -> str:
    lines = ["rank,drain_id,location,zone,ward,score,band,label,confidence,reason"]
    for row in drain_rows()[:limit]:
        sc = row.score
        assert sc is not None
        reason = sc.explanation.replace('"', "'")
        lines.append(
            f'{row.rank},{row.info.id},"{row.info.name}",{row.info.zone_name},{row.info.ward},'
            f'{sc.score:.0f},{sc.band.value},"{sc.label.value}",{sc.confidence:.2f},"{reason}"'
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- map geometry


@dataclass
class MapGeometry:
    width: float
    height: float
    blocks: list[tuple[float, float, float, float]]  # x1, y1, x2, y2
    river: list[tuple[float, float]]  # northern bank, west to east
    zone_lines: list[tuple[tuple[float, float], tuple[float, float]]]
    zone_labels: list[tuple[str, float, float]]
    street_labels: list[tuple[str, float, float, bool]]  # text, x, y, vertical


def map_geometry() -> MapGeometry:
    """City blocks between the streets, the river bank and zone boundaries, in schematic metres."""
    from drainwatch.simulate import river_y

    half_street = 22.0
    xs = [AVENUE_X0 + AVENUE_DX * i for i in range(len(AVENUES))]
    ys = [ROW_Y0 + ROW_DY * j for j in range(len(ROW_STREETS))]
    x_edges = [0.0, *xs, config.CITY_WIDTH_M]
    y_edges = [600.0, *ys, config.CITY_HEIGHT_M]
    blocks = []
    for a, b in zip(x_edges, x_edges[1:], strict=False):
        for c, d in zip(y_edges, y_edges[1:], strict=False):
            x1, x2 = a + (half_street if a > 0 else 0), b - (half_street if b < config.CITY_WIDTH_M else 0)
            y1, y2 = c + half_street, d - (half_street if d < config.CITY_HEIGHT_M else 0)
            if x2 - x1 > 40 and y2 - y1 > 40:
                blocks.append((round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)))
    river = [(float(x), round(river_y(float(x)), 1)) for x in range(0, int(config.CITY_WIDTH_M) + 1, 40)]
    w, h = config.CITY_WIDTH_M, config.CITY_HEIGHT_M
    zone_lines = [((ZONE_SPLIT_X, 640.0), (ZONE_SPLIT_X, h)), ((0.0, ZONE_SPLIT_Y), (w, ZONE_SPLIT_Y))]
    zone_labels = [
        (ZONES[0][1], 90.0, h - 70),
        (ZONES[1][1], ZONE_SPLIT_X + 300.0, h - 70),
        (ZONES[2][1], 90.0, ZONE_SPLIT_Y - 70),
        (ZONES[3][1], ZONE_SPLIT_X + 300.0, ZONE_SPLIT_Y - 70),
    ]
    street_labels = [(name, w - 40.0, y, False) for name, y in zip(ROW_STREETS, ys, strict=True)]
    return MapGeometry(w, h, blocks, river, zone_lines, zone_labels, street_labels)


def open_reports() -> list[Report]:
    with db.session_scope() as s:
        return list(
            s.exec(
                select(Report).where(
                    Report.is_history == False,  # noqa: E712
                    Report.status != ReportStatus.resolved,
                )
            ).all()
        )


# ---------------------------------------------------------------- sign in


def sign_in(username: str, password: str) -> dict | None:
    """Demo accounts only. See auth.py."""
    world()
    return auth.sign_in(username, password)


# ---------------------------------------------------------------- photos

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "static" / "uploads"
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024


def save_photo(prefix: str, filename: str, data: bytes) -> str:
    """Store an uploaded photo on this server and return its URL path."""
    ext = Path(filename).suffix.lower()
    if ext not in PHOTO_TYPES:
        raise ValueError("Use a JPG, PNG or WebP photo.")
    if len(data) > MAX_PHOTO_BYTES:
        raise ValueError("Photos must be 8 MB or smaller.")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_prefix = "".join(ch for ch in prefix if ch.isalnum() or ch in "-_")[:40]
    name = f"{safe_prefix}-{uuid.uuid4().hex[:10]}{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    return f"/static/uploads/{name}"
