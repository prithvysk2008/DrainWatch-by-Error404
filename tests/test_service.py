"""End-to-end checks of the data layer the UI depends on. Uses the real (rebuilt) demo database."""

import pytest

from drainwatch import service
from drainwatch.models import Finding, ReportSource, ReportType, Severity, Stage


@pytest.fixture(autouse=True)
def fresh():
    service.set_scenario("Heavy storm", "test")
    yield


def run_to(step: int) -> None:
    service.play("test")
    while service.state().step < step:
        service.tick(1.0)
    service.pause("test")


def test_starts_paused_at_step_zero():
    st = service.state()
    assert st.step == 0 and not st.playing
    assert service.kpis()["monitored"] == 150


def test_ranking_beats_random_mid_storm():
    run_to(14)
    v = service.validation()
    assert v["precision_at_10"] > v["random_precision_at_10"] * 3
    assert v["recall_at_20"] > v["random_recall_at_20"] * 3


def test_report_raises_priority_live():
    run_to(6)
    drain_id = service.drain_rows()[-1].info.id
    before = service.score_for(drain_id).score
    service.log_report(drain_id, ReportType.overflow, Severity.critical, ReportSource.crew, "Crew 2", "Test", "test")
    assert service.score_for(drain_id).score > before


def test_clearing_a_work_order_records_an_inspection_and_lowers_priority():
    run_to(16)
    top = service.drain_rows()[0]
    order, _ = service.dispatch(top.info.id, "test")
    service.move_order(order.id, Stage.resolved, "test", Finding.trash)
    after = service.score_for(top.info.id)
    assert after.score < top.score.score
    detail = service.drain_detail(top.info.id)
    assert any(i.finding is Finding.trash for i in detail.inspections)


def test_crew_plan_assigns_stops_without_exceeding_capacity():
    run_to(14)
    plan = service.preview_plan(n_crews=3, per_crew=2, include_ranked=True)
    assert all(len(r.stops) <= 2 for r in plan.routes)
    applied = service.apply_plan(plan, "test")
    assert applied == sum(len(r.stops) for r in plan.routes)


def test_thresholds_must_rise():
    with pytest.raises(ValueError):
        service.save_thresholds(80, 75, 85, "test")
