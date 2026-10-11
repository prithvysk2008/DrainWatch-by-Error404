"""Drain network graph. Edges point downstream: drain -> the drain it discharges into."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import networkx as nx


@dataclass(frozen=True)
class Node:
    id: str
    x_m: float
    y_m: float
    downstream_id: str | None


def build_graph(nodes: Iterable[Node]) -> nx.DiGraph:
    graph = nx.DiGraph()
    nodes = list(nodes)
    for node in nodes:
        graph.add_node(node.id, x=node.x_m, y=node.y_m)
    for node in nodes:
        if node.downstream_id is not None:
            graph.add_edge(node.id, node.downstream_id)
    if not nx.is_directed_acyclic_graph(graph):
        raise ValueError("drain network must not contain cycles")
    return graph


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def upstream(graph: nx.DiGraph, drain_id: str) -> set[str]:
    """Every drain whose water passes through drain_id."""
    return nx.ancestors(graph, drain_id)


def downstream_path(graph: nx.DiGraph, drain_id: str) -> list[str]:
    path = []
    current = drain_id
    while True:
        successors = list(graph.successors(current))
        if not successors:
            return path
        current = successors[0]
        path.append(current)


def topological_order(graph: nx.DiGraph) -> list[str]:
    """Upstream drains first, so flows can be accumulated in one pass."""
    return list(nx.topological_sort(graph))


def neighbour_map(graph: nx.DiGraph, radius_m: float) -> dict[str, list[str]]:
    """Drains within radius_m plus the drains directly upstream and downstream in the graph."""
    positions = {n: (d["x"], d["y"]) for n, d in graph.nodes(data=True)}
    ids: Sequence[str] = list(positions)
    result: dict[str, list[str]] = {}
    for drain_id in ids:
        near = {
            other
            for other in ids
            if other != drain_id and distance_m(positions[drain_id], positions[other]) <= radius_m
        }
        near.update(graph.predecessors(drain_id))
        near.update(graph.successors(drain_id))
        result[drain_id] = sorted(near)
    return result


def junction_with_upstream_count(graph: nx.DiGraph, candidates: Iterable[str], target: int) -> str:
    """The candidate whose upstream catchment size is closest to target (ties: first by id)."""
    return min(sorted(candidates), key=lambda n: abs(len(upstream(graph, n)) - target))
