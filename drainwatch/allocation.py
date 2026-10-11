"""Crew planner: assign jobs to crews by priority, then proximity. Pure functions."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from drainwatch import config


@dataclass(frozen=True)
class Job:
    key: str  # work order id, or drain id for a job that has no order yet
    drain_id: str
    x_m: float
    y_m: float
    priority: float


@dataclass(frozen=True)
class CrewSlot:
    crew_id: str
    x_m: float
    y_m: float
    capacity: int


@dataclass
class Route:
    crew_id: str
    stops: list[Job] = field(default_factory=list)
    travel_min: list[float] = field(default_factory=list)  # minutes from the previous stop

    @property
    def total_min(self) -> float:
        return sum(self.travel_min)


def travel_minutes(a: tuple[float, float], b: tuple[float, float]) -> float:
    km = math.hypot(a[0] - b[0], a[1] - b[1]) / 1000.0
    return km / config.CREW_SPEED_KMH * 60.0


def plan_routes(jobs: Sequence[Job], crews: Sequence[CrewSlot]) -> tuple[list[Route], list[Job]]:
    """Greedy plan. Highest-priority job first; it goes to the crew that can reach it soonest.

    Returns the routes and any jobs left over when every crew is full.
    """
    routes = {c.crew_id: Route(c.crew_id) for c in crews}
    position = {c.crew_id: (c.x_m, c.y_m) for c in crews}
    elapsed = {c.crew_id: 0.0 for c in crews}
    capacity = {c.crew_id: c.capacity for c in crews}
    leftover: list[Job] = []
    for job in sorted(jobs, key=lambda j: (-j.priority, j.key)):
        open_crews = [c for c in crews if len(routes[c.crew_id].stops) < capacity[c.crew_id]]
        if not open_crews:
            leftover.append(job)
            continue

        def arrival(crew: CrewSlot, job: Job = job) -> tuple[float, str]:
            return elapsed[crew.crew_id] + travel_minutes(position[crew.crew_id], (job.x_m, job.y_m)), crew.crew_id

        best = min(open_crews, key=arrival)
        leg = travel_minutes(position[best.crew_id], (job.x_m, job.y_m))
        routes[best.crew_id].stops.append(job)
        routes[best.crew_id].travel_min.append(round(leg, 1))
        elapsed[best.crew_id] += leg + 20.0  # about 20 minutes on site
        position[best.crew_id] = (job.x_m, job.y_m)
    return [routes[c.crew_id] for c in crews], leftover
