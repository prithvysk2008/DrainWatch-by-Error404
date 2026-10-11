"""Inspection priority scoring. Pure functions: no database, no UI, no clock.

Four headline factors (design document, section 10):
  water level  40  anomaly against the drain's own baseline, compared with nearby drains
  rainfall     30  storm intensity plus how long the level stays high
  history      20  days since inspection, past blockages, silt-prone
  reports      10  recency-weighted reports near the drain
x1.2 when reports and the sensor agree, plus a small tie-break for low ground and critical sites.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from drainwatch import config
from drainwatch.config import BANDS, WEIGHTS, Bands, FillThresholds, ScoringWeights
from drainwatch.models import Band, DrainScore, FillStatus, Label, SensorDiagnostic, Severity, Signals

ANOMALY_Z = 2.0  # z at or above this counts as anomalous
PERSIST_Z = 1.5
PERSIST_FULL_STEPS = 6  # one hour high = full persistence
STUCK_MIN_STEPS = 4
RAIN_FULL_MM_10MIN = 6.0
REPORT_SUPPORT = 0.3
CONGESTION_SHARE = 0.4
SEVERITY_WEIGHT = {Severity.critical: 1.0, Severity.high: 0.75, Severity.medium: 0.5}


@dataclass(frozen=True)
class ReportInput:
    x_m: float
    y_m: float
    age_min: float
    severity: Severity


@dataclass(frozen=True)
class DrainInput:
    drain_id: str
    x_m: float
    y_m: float
    zone_name: str
    max_depth_cm: float
    has_sensor: bool
    sensor_state: SensorDiagnostic  # from diagnose_sensor; ignored when has_sensor is False
    observed_cm: Sequence[float]  # history up to now, NaN where missing
    expected_cm: Sequence[float]
    spread_cm: Sequence[float]
    recent_rain_mm_10min: float
    days_since_inspection: float
    past_blockages: int
    silt_prone: bool
    recently_inspected: bool
    elevation_m: float
    zone_importance: float
    critical_site: bool


# ---------------------------------------------------------------- individual signals


def z_score(observed: float, expected: float, spread: float) -> float:
    if math.isnan(observed):
        return float("nan")
    return (observed - expected) / max(spread, 1e-6)


def anomaly_signal(z: float) -> float:
    """Clip z to 0..4, then scale to 0..1."""
    if math.isnan(z):
        return 0.0
    return min(max(z, 0.0), 4.0) / 4.0


def persistence_signal(z_history: Sequence[float]) -> tuple[float, int]:
    """Consecutive most-recent steps above PERSIST_Z. Returns (0..1, steps)."""
    run = 0
    for z in reversed(list(z_history)):
        if math.isnan(z) or z < PERSIST_Z:
            break
        run += 1
    return min(run / PERSIST_FULL_STEPS, 1.0), run


def rain_signal(recent_rain_mm_10min: float) -> float:
    return min(max(recent_rain_mm_10min, 0.0) / RAIN_FULL_MM_10MIN, 1.0)


def fill_pressure(fill_pct: float | None, thresholds: FillThresholds) -> float:
    """How far past the warning threshold the drain is, 0..1."""
    if fill_pct is None:
        return 0.0
    return min(max((fill_pct - thresholds.warning) / (100.0 - thresholds.warning), 0.0), 1.0)


def neighbour_share(neighbour_z: Sequence[float]) -> tuple[float, int, int]:
    """Share of neighbours with a usable reading that are anomalous. Returns (share, anomalous, counted)."""
    usable = [z for z in neighbour_z if not math.isnan(z)]
    if not usable:
        return 0.0, 0, 0
    high = sum(1 for z in usable if z >= ANOMALY_Z)
    return high / len(usable), high, len(usable)


def report_signal(reports: Sequence[ReportInput], x_m: float, y_m: float) -> tuple[float, int]:
    """Recency-weighted reports within REPORT_RADIUS_M, capped at 1. Returns (0..1, count)."""
    total, count = 0.0, 0
    for r in reports:
        if math.hypot(r.x_m - x_m, r.y_m - y_m) > config.REPORT_RADIUS_M or r.age_min < 0:
            continue
        total += SEVERITY_WEIGHT[r.severity] * 0.5 ** (r.age_min / config.REPORT_HALF_LIFE_MIN)
        count += 1
    return min(total, 1.0), count


def history_signal(
    days_since_inspection: float, past_blockages: int, silt_prone: bool, recently_inspected: bool
) -> float:
    if recently_inspected:
        return 0.0
    days = min(max(days_since_inspection, 0.0) / 180.0, 1.0)
    blockages = min(past_blockages / 4.0, 1.0)
    return 0.4 * days + 0.35 * blockages + 0.25 * float(silt_prone)


def consequence_signal(elevation_m: float, zone_importance: float, critical_site: bool) -> float:
    low_ground = min(max((12.0 - elevation_m) / 10.0, 0.0), 1.0)
    return 0.4 * low_ground + 0.3 * zone_importance + 0.3 * float(critical_site)


def diagnose_sensor(observed: Sequence[float], expected: Sequence[float]) -> SensorDiagnostic:
    """Judge a sensor only from its own data: no recent reading, or a flat line.

    A real ultrasonic reading always carries some noise, so four identical readings in a row are suspicious.
    The flat run counts as stuck once it has lasted an hour, or sooner if expected flows changed meanwhile.
    """
    if not observed:
        return SensorDiagnostic.no_data
    last = observed[-1]
    if math.isnan(last):
        return SensorDiagnostic.no_data
    run = 1
    for value in reversed(list(observed)[:-1]):
        if math.isnan(value) or abs(value - last) >= 0.05:
            break
        run += 1
    if run >= STUCK_MIN_STEPS:
        expected_run = list(expected)[-run:]
        if run >= PERSIST_FULL_STEPS or max(expected_run) - min(expected_run) > 3.0:
            return SensorDiagnostic.stuck
    return SensorDiagnostic.optimal


# ---------------------------------------------------------------- combination


def band_for(score: float, bands: Bands = BANDS) -> Band:
    if score >= bands.critical:
        return Band.critical
    if score >= bands.high:
        return Band.high
    if score >= bands.medium:
        return Band.medium
    return Band.low


def fill_status_for(fill_pct: float | None, thresholds: FillThresholds) -> FillStatus:
    if fill_pct is None:
        return FillStatus.unknown
    if fill_pct >= thresholds.critical:
        return FillStatus.critical
    if fill_pct >= thresholds.warning:
        return FillStatus.warning
    return FillStatus.normal


def combine(
    signals: Signals,
    water_level: float,
    sensor_usable: bool,
    weights: ScoringWeights = WEIGHTS,
) -> tuple[float, dict[str, float], bool]:
    """Returns (score, contributions in points, agreement boost applied)."""
    rainfall = 0.5 * signals.rain + 0.5 * signals.persistence
    parts = {
        "Water level": weights.water_level * water_level,
        "Rainfall": weights.rainfall * rainfall,
        "History": weights.history * signals.history,
        "Reports": weights.reports * signals.reports,
    }
    base = sum(parts.values())
    boosted = sensor_usable and signals.reports >= REPORT_SUPPORT and signals.anomaly >= 0.5
    boost_points = base * (weights.agreement_multiplier - 1.0) if boosted else 0.0
    consequence_points = weights.consequence_points * signals.consequence
    total = min(base + boost_points + consequence_points, 100.0)
    contributions = {k: round(v, 1) for k, v in parts.items()}
    contributions["Reports agree with sensor"] = round(boost_points, 1)
    contributions["Low ground or critical site"] = round(consequence_points, 1)
    return round(total, 1), contributions, boosted


def label_for(sensor_usable: bool, has_sensor: bool, signals: Signals, imputed_level: float) -> Label:
    if sensor_usable:
        if signals.anomaly >= 0.5:
            return Label.congestion if signals.neighbours >= CONGESTION_SHARE else Label.local_blockage
        return Label.unverified_report if signals.reports >= REPORT_SUPPORT else Label.normal
    if signals.reports >= REPORT_SUPPORT:
        return Label.unverified_report
    if imputed_level >= 0.25 and signals.neighbours >= CONGESTION_SHARE:
        return Label.congestion
    return Label.sensor_fault if has_sensor else Label.low_confidence


def confidence_for(
    has_sensor: bool,
    sensor_state: SensorDiagnostic,
    signals: Signals,
    neighbours_counted: int,
    report_count: int,
) -> tuple[float, str]:
    usable = has_sensor and sensor_state not in (SensorDiagnostic.stuck, SensorDiagnostic.no_data)
    agree = signals.reports >= REPORT_SUPPORT and signals.anomaly >= 0.5
    if usable:
        value = 0.85 + (0.1 if agree else 0.0) - (0.1 if neighbours_counted == 0 else 0.0)
        if agree:
            reason = (
                f"Current sensor reading, and {report_count} nearby report{'s' if report_count != 1 else ''} agree."
            )
        elif neighbours_counted == 0:
            reason = "Current sensor reading, but no nearby sensors to compare with."
        else:
            reason = f"Current sensor reading, compared with {neighbours_counted} nearby sensors."
    elif has_sensor and sensor_state is SensorDiagnostic.stuck:
        value = 0.3 + (0.15 if report_count else 0.0)
        reason = (
            "Sensor looks stuck: it keeps sending exactly the same reading. "
            "Score relies on reports, history and nearby drains."
        )
    elif has_sensor:
        value = 0.3 + (0.15 if report_count else 0.0)
        reason = "No data from this sensor. Score relies on reports, history and nearby drains."
    else:
        value = 0.4 + (0.15 if report_count else 0.0)
        reason = "No sensor on this drain. Score relies on reports, history and nearby drains."
    return round(min(value, 0.95), 2), reason


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def explain(
    d: DrainInput,
    signals: Signals,
    contributions: dict[str, float],
    sensor_usable: bool,
    delta_cm: float | None,
    persist_steps: int,
    neighbours_high: int,
    neighbours_counted: int,
    report_count: int,
    imputed_level: float,
) -> str:
    """Plain-language reason built from the three largest contributing signals."""
    candidates: list[tuple[float, str]] = []
    water_pts = contributions["Water level"]
    if sensor_usable and delta_cm is not None and signals.anomaly > 0:
        text = f"Water level is {delta_cm:.0f} cm above what this rain normally produces"
        if neighbours_counted and signals.neighbours >= CONGESTION_SHARE:
            verb = "is" if neighbours_high == 1 else "are"
            text += f", and {neighbours_high} of {neighbours_counted} nearby drains {verb} also high"
        elif neighbours_counted:
            text += ", while nearby drains look normal"
        candidates.append((water_pts, text + "."))
    elif not sensor_usable and imputed_level > 0:
        candidates.append((water_pts, "No usable sensor here, but drains around it are running high."))
    rain_pts = config.WEIGHTS.rainfall * 0.5 * signals.rain
    persist_pts = config.WEIGHTS.rainfall * 0.5 * signals.persistence
    if signals.rain > 0.05:
        rate = d.recent_rain_mm_10min * 6
        candidates.append((rain_pts, f"Rain over {d.zone_name} is {rate:.0f} mm per hour."))
    if persist_steps > 0:
        candidates.append(
            (persist_pts, f"The level has stayed high for {persist_steps * config.STEP_MINUTES} minutes.")
        )
    if report_count:
        candidates.append((contributions["Reports"], f"{_plural(report_count, 'report')} within 75 m."))
    if signals.history > 0:
        bits = []
        if d.days_since_inspection >= 365:
            bits.append("not inspected in over a year")
        elif d.days_since_inspection >= 60:
            bits.append(f"last inspected {d.days_since_inspection:.0f} days ago")
        if d.past_blockages:
            bits.append(f"{_plural(d.past_blockages, 'blockage')} in the past year")
        if d.silt_prone:
            bits.append("silt-prone")
        if bits:
            text = ", ".join(bits)
            candidates.append((contributions["History"], text[0].upper() + text[1:] + "."))
    if d.recently_inspected:
        candidates.append((0.01, "Cleared by a crew in the last two hours."))
    candidates.sort(key=lambda c: c[0], reverse=True)
    top = [text for pts, text in candidates[:3] if pts > 0]
    if not top or (signals.anomaly == 0 and report_count == 0 and sensor_usable and contributions["Water level"] < 1):
        lead = "Levels match normal behaviour for this rain."
        return " ".join([lead, *[t for t in top if not t.startswith("Water level")]][:3])
    return " ".join(top)


def score_drain(
    d: DrainInput,
    neighbour_z: Sequence[float],
    neighbour_anomaly: Sequence[float],
    reports: Sequence[ReportInput],
    thresholds: FillThresholds,
    weights: ScoringWeights = WEIGHTS,
    bands: Bands = BANDS,
) -> DrainScore:
    sensor_usable = d.has_sensor and d.sensor_state not in (SensorDiagnostic.stuck, SensorDiagnostic.no_data)
    obs = list(d.observed_cm)
    z_hist = [z_score(o, e, s) for o, e, s in zip(obs, d.expected_cm, d.spread_cm, strict=True)]
    level = obs[-1] if obs and not math.isnan(obs[-1]) else None
    expected = float(d.expected_cm[-1]) if len(d.expected_cm) else None
    fill_pct = None if level is None or not d.has_sensor else round(min(100.0, 100.0 * level / d.max_depth_cm), 1)

    if sensor_usable:
        z_now = z_hist[-1]
        anomaly = anomaly_signal(z_now)
        persistence, persist_steps = persistence_signal(z_hist)
        water_level = 0.8 * anomaly + 0.2 * fill_pressure(fill_pct, thresholds)
        imputed = 0.0
    else:
        anomaly, persistence, persist_steps = 0.0, 0.0, 0
        top_two = sorted(neighbour_anomaly, reverse=True)[:2]
        imputed = 0.5 * (sum(top_two) / len(top_two)) if top_two else 0.0
        water_level = imputed

    share, high, counted = neighbour_share(neighbour_z)
    reports_value, report_count = report_signal(reports, d.x_m, d.y_m)
    signals = Signals(
        anomaly=round(anomaly, 3),
        persistence=round(persistence, 3),
        neighbours=round(share, 3),
        reports=round(reports_value, 3),
        history=round(history_signal(d.days_since_inspection, d.past_blockages, d.silt_prone, d.recently_inspected), 3),
        consequence=round(consequence_signal(d.elevation_m, d.zone_importance, d.critical_site), 3),
        rain=round(rain_signal(d.recent_rain_mm_10min), 3),
    )
    score, contributions, boosted = combine(signals, water_level, sensor_usable, weights)
    label = label_for(sensor_usable, d.has_sensor, signals, imputed)
    confidence, reason = confidence_for(d.has_sensor, d.sensor_state, signals, counted, report_count)
    delta = None if level is None or expected is None else level - expected
    explanation = explain(
        d, signals, contributions, sensor_usable, delta, persist_steps, high, counted, report_count, imputed
    )
    status = fill_status_for(fill_pct if sensor_usable else None, thresholds)
    return DrainScore(
        drain_id=d.drain_id,
        score=score,
        band=band_for(score, bands),
        label=label,
        confidence=confidence,
        confidence_reason=reason,
        explanation=explanation,
        contributions=contributions,
        agreement_boost=boosted,
        signals=signals,
        fill_pct=fill_pct,
        level_cm=None if level is None else round(level, 1),
        expected_cm=None if expected is None else round(expected, 1),
        fill_status=status,
        sensor_ok=sensor_usable,
    )


def score_city(
    drains: Sequence[DrainInput],
    neighbours: dict[str, list[str]],
    reports: Sequence[ReportInput],
    thresholds: FillThresholds,
    weights: ScoringWeights = WEIGHTS,
    bands: Bands = BANDS,
) -> list[DrainScore]:
    """Score every drain at the current step, highest priority first."""
    z_now: dict[str, float] = {}
    for d in drains:
        usable = d.has_sensor and d.sensor_state not in (SensorDiagnostic.stuck, SensorDiagnostic.no_data)
        if usable and len(d.observed_cm):
            z_now[d.drain_id] = z_score(d.observed_cm[-1], d.expected_cm[-1], d.spread_cm[-1])
        else:
            z_now[d.drain_id] = float("nan")
    results = []
    for d in drains:
        near = [n for n in neighbours.get(d.drain_id, []) if n in z_now]
        nz = [z_now[n] for n in near]
        na = [anomaly_signal(z) for z in nz if not math.isnan(z)]
        results.append(score_drain(d, nz, na, reports, thresholds, weights, bands))
    results.sort(key=lambda s: (-s.score, s.drain_id))
    return results


# ---------------------------------------------------------------- validation


def precision_at_k(ranked_ids: Sequence[str], truth: set[str], k: int) -> float:
    top = list(ranked_ids)[:k]
    return sum(1 for d in top if d in truth) / k if k else 0.0


def recall_at_k(ranked_ids: Sequence[str], truth: set[str], k: int) -> float:
    if not truth:
        return 0.0
    top = set(list(ranked_ids)[:k])
    return len(top & truth) / len(truth)


def random_baseline(n_total: int, n_truth: int, k: int) -> tuple[float, float]:
    """Expected precision at k and recall at k for a uniformly random ranking."""
    if n_total == 0 or n_truth == 0:
        return 0.0, 0.0
    k = min(k, n_total)
    return n_truth / n_total, k / n_total
