"""Shared data models: SQLModel tables plus the computed schemas the UI reads."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, NaiveDatetime
from sqlmodel import Field, SQLModel

# ---------------------------------------------------------------- enums


class Role(StrEnum):
    operator = "operator"
    crew = "crew"


class Band(StrEnum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class FillStatus(StrEnum):
    normal = "normal"
    warning = "warning"
    critical = "critical"
    unknown = "unknown"  # no working sensor


class Label(StrEnum):
    local_blockage = "Likely local blockage"
    congestion = "Possible downstream congestion or widespread flooding"
    unverified_report = "Unverified report"
    low_confidence = "Low confidence (no sensor)"
    sensor_fault = "Low confidence (sensor fault)"
    normal = "No anomaly"


class ReportType(StrEnum):
    trash = "Trash and solid waste clog"
    overflow = "Water overtopping or flood"
    silt = "Silt or mud overfill"
    structural = "Culvert slab collapse"


class Severity(StrEnum):
    critical = "critical"  # road flooded
    high = "high"  # rising fast
    medium = "medium"  # stagnant


class ReportSource(StrEnum):
    citizen = "Citizen helpline"
    patrol = "Patrol"
    crew = "Field crew"
    operator = "Control room"


class ReportStatus(StrEnum):
    new = "new"
    dispatched = "dispatched"
    resolved = "resolved"


class Stage(StrEnum):
    pending = "pending"
    en_route = "en_route"
    active = "active"
    resolved = "resolved"


class Finding(StrEnum):
    trash = "Trash and plastics"
    silt = "Silt accumulation"
    debris = "Construction debris"
    structural = "Structural defect"
    nothing = "Nothing found"


class SensorDiagnostic(StrEnum):
    optimal = "Optimal"
    low_battery = "Low battery"
    weak_signal = "Check antenna"
    stuck = "Stuck reading"
    no_data = "No data"


class TruthKind(StrEnum):
    local_blockage = "local_blockage"
    congestion = "congestion"
    faulty_sensor = "faulty_sensor"


# ---------------------------------------------------------------- tables


class Zone(SQLModel, table=True):
    id: str = Field(primary_key=True)  # Z1..Z4
    name: str
    importance: float  # 0..1, used in the consequence tie-break


class Drain(SQLModel, table=True):
    id: str = Field(primary_key=True)  # D-001
    zone_id: str = Field(foreign_key="zone.id", index=True)
    ward: str
    name: str  # street location, for example "Canal Street at Kiln Avenue"
    x_m: float  # schematic city coordinates in metres, origin at the south-west corner
    y_m: float
    elevation_m: float
    max_depth_cm: float
    capacity_lps: float
    catchment_ha: float
    silt_prone: bool = False
    past_blockages: int = 0
    last_inspected: NaiveDatetime | None = None
    has_sensor: bool = False
    is_trunk: bool = False
    is_outfall: bool = False
    downstream_id: str | None = Field(default=None, foreign_key="drain.id")
    critical_site: str | None = None  # underpass, hospital, school, market
    site_name: str | None = None
    owner_crew_id: str | None = Field(default=None, foreign_key="crew.id")


class Sensor(SQLModel, table=True):
    serial: str = Field(primary_key=True)  # WL-0412
    drain_id: str = Field(foreign_key="drain.id", index=True)
    battery_pct: int
    signal_dbm: int
    calibration_offset_cm: float = 0.0


class SensorReading(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    drain_id: str = Field(foreign_key="drain.id", index=True)
    step: int = Field(index=True)
    ts: NaiveDatetime
    level_cm: float | None  # None means the sensor sent nothing


class RainObservation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    zone_id: str = Field(foreign_key="zone.id")
    step: int = Field(index=True)
    ts: NaiveDatetime
    mm_per_10min: float


class Report(SQLModel, table=True):
    id: str = Field(primary_key=True)  # R-1042
    drain_id: str = Field(foreign_key="drain.id", index=True)
    ts: NaiveDatetime
    type: ReportType
    severity: Severity
    source: ReportSource
    reporter: str
    description: str
    x_m: float
    y_m: float
    photo_path: str | None = None
    duplicate_of: str | None = None
    status: ReportStatus = ReportStatus.new
    resolved_at: NaiveDatetime | None = None
    is_history: bool = False  # part of the simulated 12-month record, not the live storm


class Crew(SQLModel, table=True):
    id: str = Field(primary_key=True)  # C1
    name: str
    kind: str  # Jetting truck, Desilting crew, Structural unit
    base_x: float
    base_y: float
    shift_capacity: int = 4
    available: bool = True


class WorkOrder(SQLModel, table=True):
    id: str = Field(primary_key=True)  # WO-201
    drain_id: str = Field(foreign_key="drain.id", index=True)
    stage: Stage = Stage.pending
    crew_id: str | None = Field(default=None, foreign_key="crew.id")
    task: str
    created: NaiveDatetime
    due: NaiveDatetime
    route_order: int | None = None
    notes: str = ""
    checklist_json: str = "{}"
    photo_before: str | None = None
    photo_after: str | None = None
    finding: Finding | None = None
    closed_at: NaiveDatetime | None = None


class InspectionRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    drain_id: str = Field(foreign_key="drain.id", index=True)
    ts: NaiveDatetime
    finding: Finding
    crew_id: str | None = None
    notes: str = ""
    is_history: bool = False


class User(SQLModel, table=True):
    username: str = Field(primary_key=True)
    role: Role
    display_name: str
    crew_id: str | None = Field(default=None, foreign_key="crew.id")


class AuditEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ts: NaiveDatetime
    actor: str
    action: str
    drain_id: str | None = None
    work_order_id: str | None = None
    detail: str = ""


class GroundTruth(SQLModel, table=True):
    """Hidden simulation truth. Only service.validation() reads this table."""

    id: int | None = Field(default=None, primary_key=True)
    drain_id: str = Field(foreign_key="drain.id")
    kind: TruthKind
    onset_step: int
    detail: str = ""


class Setting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str


# ---------------------------------------------------------------- computed schemas (not stored)


class Signals(BaseModel):
    """Each signal is scaled 0..1."""

    anomaly: float
    persistence: float
    neighbours: float
    reports: float
    history: float
    consequence: float
    rain: float


class DrainScore(BaseModel):
    drain_id: str
    score: float
    band: Band
    label: Label
    confidence: float
    confidence_reason: str
    explanation: str
    contributions: dict[str, float]  # points per headline factor
    agreement_boost: bool
    signals: Signals
    fill_pct: float | None
    level_cm: float | None
    expected_cm: float | None
    fill_status: FillStatus
    sensor_ok: bool


class SimState(BaseModel):
    scenario: str
    step: int
    total_steps: int
    playing: bool
    speed: float
    intensity: float
    sim_time: datetime


class Notification(BaseModel):
    id: int
    ts: datetime
    title: str
    body: str
    tone: str  # critical, warning, info, ok
    drain_id: str | None = None
