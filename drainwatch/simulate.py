"""Fictional city, storm scenarios, drain levels, reports and the hidden ground truth.

Everything is deterministic for a given seed. The simulator computes the whole 6-hour storm up
front; the clock in service.py reveals it one 10-minute step at a time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import networkx as nx
import numpy as np

from drainwatch import config
from drainwatch.config import SIM
from drainwatch.models import ReportSource, ReportType, Severity
from drainwatch.network import Node, build_graph, junction_with_upstream_count, topological_order, upstream

# ---------------------------------------------------------------- city layout

ZONES: tuple[tuple[str, str, float], ...] = (
    ("Z1", "Northbank", 0.7),
    ("Z2", "Millbrook", 0.8),
    ("Z3", "Old Quarter", 0.9),
    ("Z4", "Eastmarsh", 0.6),
)

# East-west streets, south to north. Canal Street sits closest to the river.
ROW_STREETS = (
    "Canal Street",
    "Market Road",
    "Mill Lane",
    "Station Road",
    "Chapel Row",
    "Orchard Street",
    "Hillcrest Road",
)
# North-south avenues, west to east.
AVENUES = (
    "Ferry Lane",
    "Tanner Street",
    "Kiln Avenue",
    "Weaver Street",
    "Lantern Way",
    "Cooper Street",
    "Brook Avenue",
    "Saltmarsh Way",
    "Heron Lane",
)
TRUNK_AVENUES = (1, 3, 5, 7)
AVENUE_X0, AVENUE_DX = 250.0, 437.5
ROW_Y0, ROW_DY = 750.0, 350.0
ZONE_SPLIT_X, ZONE_SPLIT_Y = 2220.0, 1625.0

SCENARIOS = ("Light rain", "Heavy storm", "Cloudburst")


def river_y(x: float) -> float:
    """Northern bank of the river that runs along the south edge of the city."""
    return 470.0 + 70.0 * math.sin(x / 650.0) + 25.0 * math.sin(x / 210.0 + 1.3)


def zone_for(x: float, y: float) -> str:
    if y >= ZONE_SPLIT_Y:
        return "Z1" if x < ZONE_SPLIT_X else "Z2"
    return "Z3" if x < ZONE_SPLIT_X else "Z4"


@dataclass
class DrainSpec:
    id: str
    zone_id: str
    ward: str
    name: str
    x: float
    y: float
    elevation: float
    max_depth_cm: float
    catchment_ha: float
    silt_prone: bool
    has_sensor: bool
    is_trunk: bool
    is_outfall: bool
    downstream_id: str | None
    critical_site: str | None = None
    site_name: str | None = None
    capacity_lps: float = 0.0  # set by calibration


@dataclass
class City:
    drains: list[DrainSpec]  # ranked drains first, then outfalls
    graph: nx.DiGraph
    index: dict[str, int]
    smax_m3: np.ndarray  # storage at full depth, per drain
    cap_m3_step: np.ndarray  # outflow capacity per 10-minute step
    base_fill: np.ndarray  # standing dry-weather water as a fraction of depth

    @property
    def n(self) -> int:
        return len(self.drains)

    @property
    def ranked(self) -> list[DrainSpec]:
        return [d for d in self.drains if not d.is_outfall]


def _ward(zone_id: str, x: float) -> str:
    zone_num = zone_id[1]
    left = 0.0 if zone_id in ("Z1", "Z3") else ZONE_SPLIT_X
    right = ZONE_SPLIT_X if zone_id in ("Z1", "Z3") else config.CITY_WIDTH_M
    third = (right - left) / 3
    letter = "ABC"[min(2, int((x - left) // third))]
    return f"Ward {zone_num}{letter}"


def build_city(seed: int = config.SEED) -> City:
    rng = np.random.default_rng(seed)
    raw: list[dict] = []

    def add(key: str, x: float, y: float, name: str, kind: str, downstream: str | None) -> None:
        raw.append({"key": key, "x": x, "y": y, "name": name, "kind": kind, "down": downstream})

    n_av, n_rows = len(AVENUES), len(ROW_STREETS)
    ax = [AVENUE_X0 + AVENUE_DX * i for i in range(n_av)]
    ry = [ROW_Y0 + ROW_DY * j for j in range(n_rows)]

    for i in TRUNK_AVENUES:
        add(f"out{i}", ax[i], river_y(ax[i]) + 30.0, f"River outfall, {AVENUES[i]}", "outfall", None)
        y_mid = (ry[0] + river_y(ax[i]) + 30.0) / 2
        add(f"tm{i}_0", ax[i], y_mid, f"{AVENUES[i]}, south of {ROW_STREETS[0]}", "trunk", f"out{i}")

    for j in range(n_rows):
        for i in range(n_av):
            here = f"x{i}_{j}"
            name = f"{ROW_STREETS[j]} at {AVENUES[i]}"
            if i in TRUNK_AVENUES:
                add(here, ax[i], ry[j], name, "trunk", f"tm{i}_{j}")
                if j + 1 < n_rows:
                    y_mid = (ry[j] + ry[j + 1]) / 2
                    between = f"{AVENUES[i]}, between {ROW_STREETS[j]} and {ROW_STREETS[j + 1]}"
                    add(f"tm{i}_{j + 1}", ax[i], y_mid, between, "trunk", here)
            else:
                if i == 0:
                    step = 1
                elif i == n_av - 1:
                    step = -1
                else:
                    step = -1 if j % 2 == 0 else 1
                mid_left = min(i, i + step)
                add(here, ax[i], ry[j], name, "lateral", f"m{mid_left}_{j}")
        for i in range(n_av - 1):
            trunk_side = i if i in TRUNK_AVENUES else i + 1
            other = i + 1 if trunk_side == i else i
            direction = "east" if ax[other] > ax[trunk_side] else "west"
            name = f"{ROW_STREETS[j]}, {direction} of {AVENUES[trunk_side]}"
            add(f"m{i}_{j}", (ax[i] + ax[i + 1]) / 2, ry[j], name, "lateral", f"x{trunk_side}_{j}")

    # Three short spurs serving critical sites.
    add("spur_underpass", ax[2] + 120.0, ry[1] - 150.0, "Station underpass", "spur", "m2_1")
    add("spur_hospital", ax[6] + 90.0, ry[5] + 140.0, "Rivermere General Hospital entrance", "spur", "m6_5")
    add("spur_school", ax[1] - 110.0, ry[4] + 130.0, "Northbank Primary School gate", "spur", "m0_4")

    # Give ranked drains stable ids ordered by zone, then north to south, then west to east.
    ranked = [r for r in raw if r["kind"] != "outfall"]
    ranked.sort(key=lambda r: (zone_for(r["x"], r["y"]), -round(r["y"]), r["x"]))
    key_to_id = {r["key"]: f"D-{k + 1:03d}" for k, r in enumerate(ranked)}
    outfalls = [r for r in raw if r["kind"] == "outfall"]
    for k, r in enumerate(sorted(outfalls, key=lambda r: r["x"])):
        key_to_id[r["key"]] = f"OF-{k + 1}"

    site_by_key = {
        "spur_underpass": ("underpass", "Station underpass"),
        "spur_hospital": ("hospital", "Rivermere General Hospital"),
        "spur_school": ("school", "Northbank Primary School"),
        "x2_1": ("market", "Old Market"),
        "x6_1": ("depot", "Eastmarsh bus depot"),
    }

    drains: list[DrainSpec] = []
    for r in ranked + sorted(outfalls, key=lambda r: r["x"]):
        x, y, kind = r["x"], r["y"], r["kind"]
        zone_id = zone_for(x, y)
        elevation = 3.0 + 20.0 * (y / config.CITY_HEIGHT_M) + float(rng.normal(0, 0.8))
        site = site_by_key.get(r["key"])
        if site and site[0] == "underpass":
            elevation -= 3.5
        if kind == "trunk":
            depth = float(rng.uniform(220, 260))
            catchment = float(rng.uniform(0.9, 1.8))
        elif kind == "spur":
            depth = float(rng.uniform(130, 160))
            catchment = float(rng.uniform(0.6, 1.1))
        else:
            depth = float(rng.uniform(120, 185))
            catchment = float(rng.uniform(0.8, 2.6))
        silt_p = 0.38 if y < 1300 else 0.2
        drains.append(
            DrainSpec(
                id=key_to_id[r["key"]],
                zone_id=zone_id,
                ward=_ward(zone_id, x),
                name=r["name"],
                x=round(x, 1),
                y=round(y, 1),
                elevation=round(max(0.5, elevation), 1),
                max_depth_cm=round(depth),
                catchment_ha=round(catchment, 2),
                silt_prone=bool(rng.random() < silt_p) and kind != "outfall",
                has_sensor=False,
                is_trunk=kind in ("trunk", "outfall"),
                is_outfall=kind == "outfall",
                downstream_id=key_to_id[r["down"]] if r["down"] else None,
                critical_site=site[0] if site else None,
                site_name=site[1] if site else None,
            )
        )

    # About 60 percent of ranked drains carry a water-level sensor. Sites and trunks are favoured.
    ranked_specs = [d for d in drains if not d.is_outfall]
    weights = np.array([3.0 if d.critical_site else 1.6 if d.is_trunk else 1.0 for d in ranked_specs])
    n_sensors = round(len(ranked_specs) * SIM.sensor_share)
    chosen = rng.choice(len(ranked_specs), size=n_sensors, replace=False, p=weights / weights.sum())
    for k in chosen:
        ranked_specs[int(k)].has_sensor = True

    graph = build_graph(Node(d.id, d.x, d.y, d.downstream_id) for d in drains)
    index = {d.id: k for k, d in enumerate(drains)}
    city = City(
        drains=drains,
        graph=graph,
        index=index,
        smax_m3=np.full(len(drains), np.inf),  # no spill limit until calibrated
        cap_m3_step=np.full(len(drains), 1e9),
        base_fill=np.zeros(len(drains)),
    )
    _calibrate(city, rng)
    return city


def _calibrate(city: City, rng: np.random.Generator) -> None:
    """Size each drain so a fault-free heavy storm peaks between 30 and 62 percent full."""
    order = [city.index[d] for d in topological_order(city.graph)]
    downstream = _downstream_index(city)
    rain = zone_rain(rain_profile("Heavy storm", 1.0), city)
    ones = np.ones((config.SCENARIO_STEPS, city.n))
    storage, outflow = _route(city, rain, ones, order, downstream, np.zeros(city.n))
    peak_s = storage.max(axis=0)
    peak_out = outflow.max(axis=0)
    target = rng.uniform(SIM.baseline_fill_low, SIM.baseline_fill_high, city.n)
    city.smax_m3 = np.maximum(peak_s / target, 1.0)
    city.cap_m3_step = peak_out * rng.uniform(SIM.capacity_headroom_low, SIM.capacity_headroom_high, city.n)
    for d, cap in zip(city.drains, city.cap_m3_step, strict=True):
        d.capacity_lps = round(float(cap) / 0.6)
    city.base_fill = rng.uniform(SIM.base_fill_low, SIM.base_fill_high, city.n)


def _downstream_index(city: City) -> np.ndarray:
    return np.array([city.index[d.downstream_id] if d.downstream_id else -1 for d in city.drains])


def _route(
    city: City,
    rain_zt: np.ndarray,
    outflow_factor: np.ndarray,
    order: list[int],
    downstream: np.ndarray,
    s0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Storage mass balance. rain_zt is (steps, zones) in mm per 10 min."""
    steps = rain_zt.shape[0]
    zone_col = np.array([int(d.zone_id[1]) - 1 for d in city.drains])
    local = rain_zt[:, zone_col] * np.array([d.catchment_ha for d in city.drains]) * SIM.runoff_m3_per_mm_ha
    storage = np.zeros((steps, city.n))
    outflow = np.zeros((steps, city.n))
    s_prev = s0.copy()
    spill_cap = city.smax_m3 * 1.05
    for t in range(steps):
        incoming = np.zeros(city.n)
        for i in order:
            factor = outflow_factor[t, i]
            available = s_prev[i] + local[t, i] + incoming[i]
            out = min(SIM.outflow_coefficient * factor * available, city.cap_m3_step[i] * factor)
            s_new = min(available - out, spill_cap[i])  # anything above the brim spills onto the street
            storage[t, i] = s_new
            outflow[t, i] = out
            if downstream[i] >= 0:
                incoming[downstream[i]] += out
        s_prev = storage[t]
    return storage, outflow


# ---------------------------------------------------------------- rain


def rain_profile(scenario: str, intensity: float, steps: int = config.SCENARIO_STEPS) -> np.ndarray:
    """City-wide rainfall in mm per 10 minutes for each step."""
    t = np.arange(steps, dtype=float)

    def bump(peak: float, centre: float, width: float) -> np.ndarray:
        return peak * np.exp(-0.5 * ((t - centre) / width) ** 2)

    if scenario == "Light rain":
        rain = bump(1.3, 12, 7) + 0.25 * ((t >= 2) & (t <= 28))
    elif scenario == "Heavy storm":
        rain = bump(5.8, 12, 4.5) + bump(3.4, 22, 3.0)
    elif scenario == "Cloudburst":
        rain = bump(3.0, 7, 3.0) + bump(14.0, 13, 2.2) + bump(4.0, 19, 3.0)
    else:
        raise ValueError(f"unknown scenario {scenario!r}")
    rain[t < 2] *= 0.15
    return np.round(rain * intensity, 2)


def zone_rain(city_rain: np.ndarray, city: City | None = None) -> np.ndarray:
    """(steps, zones) rainfall, with each zone a little wetter or drier than the city average."""
    return np.outer(city_rain, np.array(SIM.zone_rain_multipliers))


# ---------------------------------------------------------------- faults and ground truth


@dataclass
class Faults:
    blockages: dict[str, int]  # drain id -> onset step
    congestion_junction: str
    congestion_members: frozenset[str]
    congestion_onset: int
    faulty_sensors: dict[str, tuple[str, int]]  # drain id -> (stuck_high | flatline | dropout, onset)
    cleared: dict[str, int] = field(default_factory=dict)  # drain id -> step a crew cleared it
    sensor_reset: dict[str, int] = field(default_factory=dict)


def plant_faults(city: City, seed: int = config.SEED) -> Faults:
    rng = np.random.default_rng(seed + 1)
    trunk_candidates = [d.id for d in city.ranked if d.is_trunk and d.y > 1100]
    junction = junction_with_upstream_count(city.graph, trunk_candidates, SIM.congestion_upstream_target)
    members = frozenset(upstream(city.graph, junction) | {junction})

    eligible = [d for d in city.ranked if d.id not in members and not d.critical_site]
    with_sensor = [d.id for d in eligible if d.has_sensor]
    without_sensor = [d.id for d in eligible if not d.has_sensor]
    n_sensor = 7
    blocked = list(rng.choice(with_sensor, n_sensor, replace=False))
    blocked += list(rng.choice(without_sensor, SIM.n_local_blockages - n_sensor, replace=False))
    onsets = [0, 0, 0, 0] + [int(v) for v in rng.integers(3, 15, SIM.n_local_blockages - 4)]
    rng.shuffle(onsets)
    blockages = {str(d): o for d, o in zip(blocked, onsets, strict=True)}

    spare = [d for d in with_sensor if d not in blockages]
    faulty_ids = rng.choice(spare, SIM.n_faulty_sensors, replace=False)
    kinds = ("stuck_high", "flatline", "dropout")
    faulty = {str(d): (kinds[k], (4, 8, 12)[k]) for k, d in enumerate(faulty_ids)}
    return Faults(blockages, junction, members, 9, faulty)


def outflow_factor_matrix(city: City, faults: Faults, steps: int = config.SCENARIO_STEPS) -> np.ndarray:
    factor = np.ones((steps, city.n))
    for drain_id, onset in faults.blockages.items():
        end = faults.cleared.get(drain_id, steps)
        if end > onset:
            factor[onset:end, city.index[drain_id]] *= SIM.blocked_outflow_factor
    congestion_end = faults.cleared.get(faults.congestion_junction, steps)
    if congestion_end > faults.congestion_onset:
        for drain_id in faults.congestion_members:
            factor[faults.congestion_onset : congestion_end, city.index[drain_id]] *= SIM.congestion_outflow_factor
    return factor


# ---------------------------------------------------------------- a storm run


@dataclass
class Run:
    scenario: str
    city_rain: np.ndarray  # (steps,)
    rain_zt: np.ndarray  # (steps, zones)
    true_cm: np.ndarray  # (steps, n)
    expected_cm: np.ndarray  # (steps, n) fault-free behaviour for the same rain
    observed_cm: np.ndarray  # (steps, n) what sensors report; NaN where no sensor or no data
    spread_cm: np.ndarray  # (steps, n) normal spread used to scale anomalies
    velocity_ms: np.ndarray  # (steps, n)


def simulate_run(
    city: City,
    faults: Faults,
    scenario: str,
    intensity_by_step: np.ndarray,
    seed: int = config.SEED,
) -> Run:
    steps = config.SCENARIO_STEPS
    base_profile = rain_profile(scenario, 1.0)
    city_rain = np.round(base_profile * intensity_by_step, 2)
    rain_zt = zone_rain(city_rain)
    order = [city.index[d] for d in topological_order(city.graph)]
    downstream = _downstream_index(city)
    depth = np.array([d.max_depth_cm for d in city.drains])

    clean = np.ones((steps, city.n))
    s_expected, _ = _route(city, rain_zt, clean, order, downstream, np.zeros(city.n))
    factor = outflow_factor_matrix(city, faults, steps)
    s_true, out_true = _route(city, rain_zt, factor, order, downstream, np.zeros(city.n))

    base = city.base_fill * depth
    expected_cm = np.minimum(base + s_expected / city.smax_m3 * depth, depth)  # above the brim, water spills
    true_cm = np.minimum(base + s_true / city.smax_m3 * depth, depth)

    noise = np.random.default_rng(seed + 2).normal(0, SIM.noise_cm, (steps, city.n))
    observed = np.clip(true_cm + noise, 0, None)
    has_sensor = np.array([d.has_sensor for d in city.drains])
    observed[:, ~has_sensor] = np.nan
    for drain_id, (kind, onset) in faults.faulty_sensors.items():
        i = city.index[drain_id]
        end = faults.sensor_reset.get(drain_id, steps)
        if end <= onset:
            continue
        if kind == "stuck_high":
            observed[onset:end, i] = round(0.93 * depth[i], 1)
        elif kind == "flatline":
            observed[onset:end, i] = observed[onset - 1, i] if onset > 0 else observed[0, i]
        else:
            observed[onset:end, i] = np.nan
    observed = np.round(observed, 1)

    spread = SIM.spread_floor_cm + SIM.spread_fraction * expected_cm
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(s_true > 0, out_true / (SIM.outflow_coefficient * np.maximum(s_true + out_true, 1e-6)), 1.0)
    load = np.clip(out_true / city.cap_m3_step, 0, 1)
    velocity = np.clip(1.9 * np.clip(ratio, 0, 1) * (0.35 + 0.65 * load), 0.05, 2.2)
    return Run(scenario, city_rain, rain_zt, true_cm, expected_cm, observed, spread, np.round(velocity, 2))


# ---------------------------------------------------------------- reports


@dataclass
class SimReport:
    step: int
    drain_id: str
    type: ReportType
    severity: Severity
    source: ReportSource
    reporter: str
    description: str
    x: float
    y: float


DESCRIPTIONS = {
    ReportType.trash: "Plastic and leaves packed against the inlet grate. Water is ponding at the kerb.",
    ReportType.overflow: "Water is coming up through the cover and spreading across the road.",
    ReportType.silt: "Inlet half full of mud. Water drains away very slowly.",
    ReportType.structural: "Cover slab is cracked and tilting. Debris is falling into the drain.",
}


def generate_reports(city: City, faults: Faults, scenario: str, seed: int = config.SEED) -> list[SimReport]:
    """Reports that will arrive during the storm. Light rain produces fewer of them."""
    rng = np.random.default_rng(seed + 3 + SCENARIOS.index(scenario))
    steps = config.SCENARIO_STEPS
    reports: list[SimReport] = []
    by_id = {d.id: d for d in city.drains}
    p_report = SIM.report_probability * (0.4 if scenario == "Light rain" else 1.0)

    def make(drain_id: str, step: int, kind: ReportType, severity: Severity) -> SimReport:
        d = by_id[drain_id]
        source = ReportSource.citizen if rng.random() < 0.7 else ReportSource.patrol
        reporter = (
            f"Caller {int(rng.integers(100, 999))}"
            if source is ReportSource.citizen
            else (f"Patrol unit {int(rng.integers(1, 9))}")
        )
        angle, dist = rng.uniform(0, 2 * math.pi), rng.uniform(0, 30)
        return SimReport(
            step,
            drain_id,
            kind,
            severity,
            source,
            reporter,
            DESCRIPTIONS[kind],
            round(d.x + dist * math.cos(angle), 1),
            round(d.y + dist * math.sin(angle), 1),
        )

    for drain_id, onset in sorted(faults.blockages.items()):
        if rng.random() < p_report:
            step = onset + int(rng.integers(3, 10))
            if step < steps:
                kind = ReportType.trash if rng.random() < 0.6 else ReportType.silt
                reports.append(make(drain_id, step, kind, Severity.high))

    members = sorted(faults.congestion_members)
    for k in range(2):
        drain_id = members[int(rng.integers(0, len(members)))]
        step = faults.congestion_onset + 4 + 3 * k
        reports.append(make(drain_id, step, ReportType.overflow, Severity.critical))

    clean = [d.id for d in city.ranked if d.id not in faults.blockages and d.id not in faults.congestion_members]
    for drain_id in rng.choice(clean, SIM.n_false_reports, replace=False):
        kind = [ReportType.trash, ReportType.overflow, ReportType.silt, ReportType.structural][int(rng.integers(0, 4))]
        severity = Severity.medium if rng.random() < 0.6 else Severity.high
        reports.append(make(str(drain_id), int(rng.integers(2, 31)), kind, severity))

    originals = list(reports)
    for k in rng.choice(len(originals), min(SIM.n_duplicate_reports, len(originals)), replace=False):
        original = originals[int(k)]
        step = min(steps - 1, original.step + int(rng.integers(1, 4)))
        reports.append(make(original.drain_id, step, original.type, original.severity))

    reports.sort(key=lambda r: (r.step, r.drain_id))
    return reports


# ---------------------------------------------------------------- 12-month history


@dataclass
class HistoryEvent:
    drain_id: str
    reported: datetime
    resolved: datetime
    type: ReportType
    severity: Severity
    finding: str  # Finding value


def generate_history(city: City, now: datetime, seed: int = config.SEED) -> list[HistoryEvent]:
    """A simulated year of reports and inspections. Monsoon months (June to September) are busier."""
    rng = np.random.default_rng(seed + 9)
    ranked = city.ranked
    propensity = np.array(
        [1.0 + 2.2 * d.silt_prone + 1.2 * (d.elevation < 8) + 1.5 * bool(d.critical_site) for d in ranked]
    )
    ward_speed = {w: float(rng.uniform(0.75, 1.4)) for w in sorted({d.ward for d in ranked})}
    findings = ["Trash and plastics", "Silt accumulation", "Construction debris", "Structural defect", "Nothing found"]
    finding_p = [0.42, 0.28, 0.12, 0.06, 0.12]
    type_for = {
        "Trash and plastics": ReportType.trash,
        "Silt accumulation": ReportType.silt,
        "Construction debris": ReportType.trash,
        "Structural defect": ReportType.structural,
        "Nothing found": ReportType.overflow,
    }
    events: list[HistoryEvent] = []
    for day in range(365, 1, -1):
        date = now - timedelta(days=day)
        monsoon = 6 <= date.month <= 9
        expected = 1.25 if monsoon else 0.35
        for _ in range(int(rng.poisson(expected))):
            k = int(rng.choice(len(ranked), p=propensity / propensity.sum()))
            d = ranked[k]
            finding = findings[int(rng.choice(len(findings), p=finding_p))]
            reported = date.replace(hour=int(rng.integers(6, 22)), minute=int(rng.integers(0, 60)))
            minutes = float(rng.gamma(3.0, 16.0)) * ward_speed[d.ward] * (0.8 if monsoon else 1.1)
            severity = [Severity.medium, Severity.high, Severity.critical][int(rng.choice(3, p=[0.5, 0.35, 0.15]))]
            events.append(
                HistoryEvent(
                    d.id,
                    reported,
                    reported + timedelta(minutes=round(minutes + 12)),
                    type_for[finding],
                    severity,
                    finding,
                )
            )
    return events


def scenario_start(today: datetime) -> datetime:
    return today.replace(hour=config.SCENARIO_START_HOUR, minute=0, second=0, microsecond=0)


def step_time(start: datetime, step: int) -> datetime:
    return start + timedelta(minutes=config.STEP_MINUTES * step)
