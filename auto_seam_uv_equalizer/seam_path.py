"""Linear-memory candidate scoring and continuous seam path search."""
from __future__ import annotations
from heapq import heappop, heappush
from math import acos

def shortest_path(adjacency, starts, goals, edge_cost, max_hops=24):
    """Multi-source Dijkstra over a vertex adjacency map without quadratic scans."""
    goals, heap, best, previous = set(goals), [], {}, {}
    for start in starts:
        best[start] = 0.0; heappush(heap, (0.0, 0, start))
    reached = None
    while heap:
        cost, hops, vertex = heappop(heap)
        if cost != best.get(vertex) or hops > max_hops: continue
        if vertex in goals and hops: reached = vertex; break
        for neighbour, edge_index in adjacency.get(vertex, ()):
            new_cost = cost + max(1e-9, edge_cost(edge_index))
            if new_cost < best.get(neighbour, float("inf")):
                best[neighbour] = new_cost; previous[neighbour] = (vertex, edge_index)
                heappush(heap, (new_cost, hops + 1, neighbour))
    if reached is None: return []
    path = []
    while reached not in starts:
        reached, edge_index = previous[reached]; path.append(edge_index)
    return list(reversed(path))

def continuity_penalty(previous_direction, direction, bias):
    if previous_direction is None: return 0.0
    dot = max(-1.0, min(1.0, sum(a*b for a,b in zip(previous_direction, direction))))
    return bias * acos(abs(dot))
