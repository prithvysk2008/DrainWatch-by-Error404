import math

import pytest

from drainwatch import scoring
from drainwatch.config import FillThresholds, ScoringWeights
from drainwatch.models import Band, FillStatus, Label, SensorDiagnostic, Severity, Signals
from drainwatch.scoring import DrainInput, ReportInput

NAN = float("nan")


def make_drain(**overrides) -> DrainInput:
    base = dict(
        drain_id="D-001",
        x_m=0.0,
        y_m=0.0,
        zone_name="Old Quarter",
        max_depth_cm=200.0,
        has_sensor=True,
        sensor_state=SensorDiagnostic.optimal,
        observed_cm=[40.0, 41.0, 40.5],
        expected_cm=[40.0, 41.0, 40.5],
        spread_cm=[5.0, 5.0, 5.0],
        recent_rain_mm_10min=0.0,
        days_since_inspection=10.0,
        past_blockages=0,
        silt_prone=False,
        recently_inspected=False,
        elevation_m=15.0,
        zone_importance=0.5,
        critical_site=False,
    )
    base.update(overrides)
    return DrainInput(**base)


def score(d: DrainInput, neighbour_z=(), reports=()):
    na = [scoring.anomaly_signal(z) for z in neighbour_z if not math.isnan(z)]
    return scoring.score_drain(d, list(neighbour_z), na, list(reports), FillThresholds())


# ------------------------------------------------------------ signals


def test_anomaly_clips_to_zero_and_four():
    assert scoring.anomaly_signal(-3.0) == 0.0
    assert scoring.anomaly_signal(2.0) == 0.5
    assert scoring.anomaly_signal(9.0) == 1.0
    assert scoring.anomaly_signal(NAN) == 0.0


def test_z_score_uses_spread():
    assert scoring.z_score(60.0, 40.0, 5.0) == pytest.approx(4.0)
    assert math.isnan(scoring.z_score(NAN, 40.0, 5.0))


def test_persistence_counts_recent_high_steps_only():
    value, steps = scoring.persistence_signal([3.0, 0.2, 2.0, 2.5, 1.9])
    assert steps == 3
    assert value == pytest.approx(0.5)
    assert scoring.persistence_signal([2.0] * 10) == (1.0, 10)


def test_report_signal_respects_radius_and_decay():
    near_new = ReportInput(10.0, 0.0, 0.0, Severity.high)
    near_old = ReportInput(10.0, 0.0, 90.0, Severity.high)
    far = ReportInput(500.0, 0.0, 0.0, Severity.critical)
    value, count = scoring.report_signal([near_new, far], 0.0, 0.0)
    assert count == 1 and value == pytest.approx(0.75)
    value_old, _ = scoring.report_signal([near_old], 0.0, 0.0)
    assert value_old == pytest.approx(0.375)  # one half-life later
    capped, _ = scoring.report_signal([ReportInput(0, 0, 0, Severity.critical)] * 5, 0, 0)
    assert capped == 1.0


def test_history_is_zero_right_after_inspection():
    assert scoring.history_signal(400, 5, True, recently_inspected=True) == 0.0
    assert scoring.history_signal(400, 5, True, recently_inspected=False) == pytest.approx(1.0)


def test_neighbour_share_ignores_missing_readings():
    share, high, counted = scoring.neighbour_share([3.0, 0.1, NAN, 2.5])
    assert (high, counted) == (2, 3)
    assert share == pytest.approx(2 / 3)


# ------------------------------------------------------------ bands, labels, combination


@pytest.mark.parametrize(
    ("value", "band"),
    [(100, Band.critical), (75, Band.critical), (74.9, Band.high), (55, Band.high), (35, Band.medium), (0, Band.low)],
)
def test_band_edges(value, band):
    assert scoring.band_for(value) is band


def test_fill_status_uses_thresholds():
    th = FillThresholds(unimpeded=45, warning=75, critical=85)
    assert scoring.fill_status_for(None, th) is FillStatus.unknown
    assert scoring.fill_status_for(74.9, th) is FillStatus.normal
    assert scoring.fill_status_for(75, th) is FillStatus.warning
    assert scoring.fill_status_for(85, th) is FillStatus.critical


def test_agreement_boost_needs_both_reports_and_sensor():
    signals = Signals(anomaly=1.0, persistence=1.0, neighbours=0.0, reports=0.5, history=0.5, consequence=0.0, rain=1.0)
    boosted, _, applied = scoring.combine(signals, 1.0, sensor_usable=True)
    plain, _, not_applied = scoring.combine(signals, 1.0, sensor_usable=False)
    assert applied and not not_applied
    assert boosted == pytest.approx(min(plain * 1.2, 100))


def test_score_is_capped_at_100():
    signals = Signals(anomaly=1, persistence=1, neighbours=0, reports=1, history=1, consequence=1, rain=1)
    total, _, _ = scoring.combine(signals, 1.0, True, ScoringWeights())
    assert total == 100.0


def test_normal_drain_scores_low_and_says_so():
    result = score(make_drain(), neighbour_z=[0.1, -0.2])
    assert result.band is Band.low
    assert result.label is Label.normal
    assert result.explanation.startswith("Levels match normal behaviour")


def test_isolated_rise_is_a_local_blockage():
    d = make_drain(
        observed_cm=[40, 70, 90, 110, 120, 125, 130],
        expected_cm=[40, 45, 50, 55, 55, 52, 50],
        spread_cm=[5.0] * 7,
        recent_rain_mm_10min=5.0,
        days_since_inspection=200,
        past_blockages=3,
        silt_prone=True,
    )
    result = score(d, neighbour_z=[0.2, -0.5, 0.4])
    assert result.label is Label.local_blockage
    assert result.band in (Band.critical, Band.high)
    assert "nearby drains look normal" in result.explanation


def test_widespread_rise_is_labelled_congestion():
    d = make_drain(observed_cm=[40, 80, 95], expected_cm=[40, 50, 55], spread_cm=[5.0] * 3)
    result = score(d, neighbour_z=[3.0, 2.5, 4.0, 0.1])
    assert result.label is Label.congestion


def test_report_without_sensor_support_is_unverified():
    report = ReportInput(0.0, 0.0, 5.0, Severity.critical)
    result = score(make_drain(), reports=[report])
    assert result.label is Label.unverified_report
    assert not result.agreement_boost


def test_no_sensor_lowers_confidence_and_says_why():
    d = make_drain(has_sensor=False, observed_cm=[NAN] * 3)
    result = score(d)
    assert result.label is Label.low_confidence
    assert result.confidence < 0.6
    assert "No sensor" in result.confidence_reason
    assert result.fill_status is FillStatus.unknown


def test_reports_and_sensor_agreeing_raise_score_and_confidence():
    d = make_drain(observed_cm=[40, 80, 100], expected_cm=[40, 45, 50], spread_cm=[5.0] * 3)
    alone = score(d, neighbour_z=[0.0])
    agreed = score(d, neighbour_z=[0.0], reports=[ReportInput(5.0, 5.0, 10.0, Severity.high)])
    assert agreed.agreement_boost
    assert agreed.score > alone.score
    assert agreed.confidence > alone.confidence


def test_score_city_orders_by_score():
    normal = make_drain(drain_id="D-002")
    blocked = make_drain(
        drain_id="D-001",
        observed_cm=[40, 90, 120],
        expected_cm=[40, 45, 50],
        spread_cm=[5.0] * 3,
        recent_rain_mm_10min=4.0,
    )
    results = scoring.score_city([normal, blocked], {"D-001": ["D-002"], "D-002": ["D-001"]}, [], FillThresholds())
    assert [r.drain_id for r in results] == ["D-001", "D-002"]


# ------------------------------------------------------------ sensor diagnostics


def test_noisy_sensor_is_optimal():
    assert scoring.diagnose_sensor([40.1, 41.3, 39.8, 40.6], [40, 41, 40, 41]) is SensorDiagnostic.optimal


def test_missing_latest_reading_is_no_data():
    assert scoring.diagnose_sensor([40.1, NAN], [40, 41]) is SensorDiagnostic.no_data


def test_flat_line_while_flows_change_is_stuck():
    assert scoring.diagnose_sensor([50.0] * 4, [40, 50, 60, 70]) is SensorDiagnostic.stuck


def test_flat_line_for_an_hour_is_stuck_even_in_dry_weather():
    assert scoring.diagnose_sensor([50.0] * 6, [40.0] * 6) is SensorDiagnostic.stuck
    assert scoring.diagnose_sensor([50.0] * 4, [40.0] * 4) is SensorDiagnostic.optimal


# ------------------------------------------------------------ validation metrics


def test_precision_and_recall():
    ranked = ["a", "b", "c", "d"]
    truth = {"a", "c", "z"}
    assert scoring.precision_at_k(ranked, truth, 2) == 0.5
    assert scoring.recall_at_k(ranked, truth, 4) == pytest.approx(2 / 3)
    assert scoring.recall_at_k(ranked, set(), 4) == 0.0


def test_random_baseline_is_exact():
    p, r = scoring.random_baseline(150, 15, 10)
    assert p == pytest.approx(0.1)
    _, r20 = scoring.random_baseline(150, 15, 20)
    assert r20 == pytest.approx(20 / 150)
