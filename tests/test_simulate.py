import networkx as nx
import numpy as np
import pytest

from drainwatch import config
from drainwatch.network import upstream
from drainwatch.simulate import (
    SCENARIOS,
    build_city,
    generate_reports,
    plant_faults,
    rain_profile,
    simulate_run,
)


@pytest.fixture(scope="module")
def city():
    return build_city(config.SEED)


@pytest.fixture(scope="module")
def faults(city):
    return plant_faults(city, config.SEED)


def test_city_has_150_drains_and_about_60_percent_sensors(city):
    assert len(city.ranked) == 150
    share = sum(d.has_sensor for d in city.ranked) / len(city.ranked)
    assert share == pytest.approx(0.6, abs=0.01)
    assert {d.zone_id for d in city.ranked} == {"Z1", "Z2", "Z3", "Z4"}


def test_network_is_a_forest_ending_at_outfalls(city):
    assert nx.is_directed_acyclic_graph(city.graph)
    for d in city.ranked:
        assert city.graph.out_degree(d.id) == 1
    sinks = [n for n in city.graph.nodes if city.graph.out_degree(n) == 0]
    assert sinks and all(n.startswith("OF-") for n in sinks)


def test_drain_ids_are_unique_and_formatted(city):
    ids = [d.id for d in city.ranked]
    assert len(set(ids)) == len(ids)
    assert all(i.startswith("D-") and len(i) == 5 for i in ids)


def test_city_is_deterministic():
    a, b = build_city(config.SEED), build_city(config.SEED)
    assert [(d.id, d.x, d.y, d.has_sensor) for d in a.drains] == [(d.id, d.x, d.y, d.has_sensor) for d in b.drains]


def test_planted_faults_match_the_brief(city, faults):
    assert len(faults.blockages) == 10
    assert len(faults.faulty_sensors) == 3
    upstream_count = len(upstream(city.graph, faults.congestion_junction))
    assert 8 <= upstream_count <= 16
    assert not set(faults.blockages) & faults.congestion_members


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_rain_profiles_are_positive_and_ordered(scenario):
    rain = rain_profile(scenario, 1.0)
    assert rain.shape == (config.SCENARIO_STEPS,)
    assert (rain >= 0).all()
    assert rain.max() > 0


def test_storms_get_stronger():
    peaks = [rain_profile(s, 1.0).max() for s in SCENARIOS]
    assert peaks == sorted(peaks)


def test_fault_free_heavy_storm_stays_below_warning(city, faults):
    run = simulate_run(city, faults, "Heavy storm", np.ones(config.SCENARIO_STEPS))
    depth = np.array([d.max_depth_cm for d in city.drains])
    peak_fill = (run.expected_cm / depth).max(axis=0)
    assert peak_fill.max() < 0.75


def test_blockages_raise_levels_above_expected(city, faults):
    run = simulate_run(city, faults, "Heavy storm", np.ones(config.SCENARIO_STEPS))
    for drain_id in faults.blockages:
        i = city.index[drain_id]
        assert run.true_cm[20, i] > run.expected_cm[20, i] + 10


def test_clearing_a_blockage_restores_flow_and_keeps_the_past(city, faults):
    intensity = np.ones(config.SCENARIO_STEPS)
    before = simulate_run(city, faults, "Heavy storm", intensity)
    drain_id = next(iter(faults.blockages))
    faults.cleared[drain_id] = 15
    try:
        after = simulate_run(city, faults, "Heavy storm", intensity)
    finally:
        del faults.cleared[drain_id]
    i = city.index[drain_id]
    np.testing.assert_allclose(after.observed_cm[:15], before.observed_cm[:15], equal_nan=True)
    assert after.true_cm[25, i] < before.true_cm[25, i]


def test_sensorless_drains_report_nothing(city, faults):
    run = simulate_run(city, faults, "Light rain", np.ones(config.SCENARIO_STEPS))
    for d in city.ranked:
        if not d.has_sensor:
            assert np.isnan(run.observed_cm[:, city.index[d.id]]).all()


def test_reports_include_false_and_duplicate_reports(city, faults):
    reports = generate_reports(city, faults, "Heavy storm", config.SEED)
    on_clean = [
        r for r in reports if r.drain_id not in faults.blockages and r.drain_id not in faults.congestion_members
    ]
    assert len(on_clean) >= config.SIM.n_false_reports
    assert all(0 <= r.step < config.SCENARIO_STEPS for r in reports)
    assert reports == sorted(reports, key=lambda r: (r.step, r.drain_id))
