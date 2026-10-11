"""Every tunable number in one place: scoring weights, bands, thresholds, simulation constants."""

from __future__ import annotations

from dataclasses import dataclass, field

SEED = 404
STEP_MINUTES = 10
SCENARIO_STEPS = 36  # 6 hours of 10-minute steps
SCENARIO_START_HOUR = 15  # simulated storms start at 15:00 on the current day

CITY_NAME = "Rivermere"
CITY_WIDTH_M = 4000.0
CITY_HEIGHT_M = 3000.0

NEIGHBOUR_RADIUS_M = 300.0
REPORT_RADIUS_M = 75.0
REPORT_HALF_LIFE_MIN = 90.0
RECENT_INSPECTION_MIN = 120  # a drain cleared within this window gets no history weight


@dataclass(frozen=True)
class ScoringWeights:
    """The four headline factors from the design document, in points out of 100."""

    water_level: float = 40.0
    rainfall: float = 30.0
    history: float = 20.0
    reports: float = 10.0
    agreement_multiplier: float = 1.2  # applied when reports and the sensor agree
    consequence_points: float = 4.0  # small tie-break for low ground and critical sites


@dataclass(frozen=True)
class Bands:
    critical: float = 75.0
    high: float = 55.0
    medium: float = 35.0


@dataclass
class FillThresholds:
    """Percent of drain depth. One profile drives the map legend, badges and the sensors page."""

    unimpeded: float = 45.0
    warning: float = 75.0
    critical: float = 85.0


@dataclass(frozen=True)
class ThreatLevel:
    level: int
    name: str
    min_rain_mm_h: float
    min_share_above_warning: float


THREAT_LEVELS: tuple[ThreatLevel, ...] = (
    ThreatLevel(1, "Normal", 0.0, 0.0),
    ThreatLevel(2, "Advisory", 7.5, 0.05),
    ThreatLevel(3, "Flood watch", 25.0, 0.15),
    ThreatLevel(4, "Flash flood warning", 50.0, 0.30),
)

# Response time targets per priority band, in simulated minutes.
SLA_MINUTES = {"critical": 60, "high": 120, "medium": 240, "low": 480}
CREW_SPEED_KMH = 20.0
INSPECTIONS_TARGET_PER_SHIFT = 20


@dataclass(frozen=True)
class SimConstants:
    runoff_m3_per_mm_ha: float = 6.0
    outflow_coefficient: float = 0.55
    blocked_outflow_factor: float = 0.3
    congestion_outflow_factor: float = 0.6
    noise_cm: float = 1.6
    spread_floor_cm: float = 2.5
    spread_fraction: float = 0.08
    baseline_fill_low: float = 0.24  # storm water at the peak of a fault-free heavy storm, fraction of depth
    baseline_fill_high: float = 0.50
    base_fill_low: float = 0.05  # standing dry-weather water
    base_fill_high: float = 0.13
    capacity_headroom_low: float = 1.6  # outflow capacity relative to the heavy-storm peak flow
    capacity_headroom_high: float = 2.6
    n_local_blockages: int = 10
    congestion_upstream_target: int = 12
    n_faulty_sensors: int = 3
    n_false_reports: int = 8
    n_duplicate_reports: int = 3
    report_probability: float = 0.5
    sensor_share: float = 0.6
    zone_rain_multipliers: tuple[float, ...] = field(default=(1.12, 1.0, 0.92, 1.05))


WEIGHTS = ScoringWeights()
BANDS = Bands()
SIM = SimConstants()
