from drainwatch.allocation import CrewSlot, Job, plan_routes, travel_minutes


def test_travel_minutes_at_twenty_kmh():
    assert travel_minutes((0, 0), (2000, 0)) == 6.0


def test_highest_priority_goes_first_to_the_nearest_crew():
    jobs = [Job("a", "D-1", 100, 0, 50), Job("b", "D-2", 5000, 0, 90)]
    crews = [CrewSlot("C1", 0, 0, 2), CrewSlot("C2", 5000, 0, 2)]
    routes, leftover = plan_routes(jobs, crews)
    by_crew = {r.crew_id: [j.key for j in r.stops] for r in routes}
    assert by_crew == {"C1": ["a"], "C2": ["b"]}
    assert leftover == []


def test_capacity_is_respected_and_extra_jobs_are_left_over():
    jobs = [Job(str(k), f"D-{k}", k * 10.0, 0, 100 - k) for k in range(5)]
    routes, leftover = plan_routes(jobs, [CrewSlot("C1", 0, 0, 2)])
    assert [j.key for j in routes[0].stops] == ["0", "1"]
    assert [j.key for j in leftover] == ["2", "3", "4"]


def test_no_crews_means_everything_is_left_over():
    jobs = [Job("a", "D-1", 0, 0, 10)]
    routes, leftover = plan_routes(jobs, [])
    assert routes == [] and leftover == jobs
