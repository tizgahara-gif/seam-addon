"""Linear-memory candidate scoring and continuous seam path search."""
from __future__ import annotations
from heapq import heappop, heappush
from math import acos

def _unit(vector):
    values = tuple(vector) if hasattr(vector, "__iter__") else tuple(vector.xyz)
    length = sum(value * value for value in values) ** .5
    return tuple(value / length for value in values) if length > 1e-12 else None

def shortest_path(adjacency, starts, goals, edge_cost, max_hops=24, positions=None,
                  straightness_bias=0.0):
    """Direction-aware multi-source Dijkstra.

    The state contains the incoming edge rather than only the vertex.  Thus two
    arrivals at a vertex with different directions remain distinct and the turn
    penalty can influence the path that is actually selected.
    """
    goals, heap, best, previous = set(goals), [], {}, {}
    for start in starts:
        state = (None, start)
        best[state] = 0.0; heappush(heap, (0.0, 0, -1, start))
    reached = None
    while heap:
        cost, hops, incoming, vertex = heappop(heap)
        state = (None if incoming < 0 else incoming, vertex)
        if cost != best.get(state) or hops > max_hops: continue
        if vertex in goals and hops: reached = state; break
        for neighbour, edge_index in adjacency.get(vertex, ()):
            turn = 0.0
            if positions is not None and incoming >= 0:
                prior_vertex = previous[state][0][1]
                a = positions[vertex] - positions[prior_vertex]
                b = positions[neighbour] - positions[vertex]
                direction_a, direction_b = _unit(a), _unit(b)
                if direction_a is not None and direction_b is not None:
                    turn = continuity_penalty(direction_a, direction_b, straightness_bias)
            new_cost = cost + max(1e-9, edge_cost(edge_index)) + turn
            next_state = (edge_index, neighbour)
            if new_cost < best.get(next_state, float("inf")):
                best[next_state] = new_cost; previous[next_state] = (state, edge_index)
                heappush(heap, (new_cost, hops + 1, edge_index, neighbour))
    if reached is None: return []
    path = []
    while reached[0] is not None:
        reached, edge_index = previous[reached]; path.append(edge_index)
    return list(reversed(path))

def continuity_penalty(previous_direction, direction, bias):
    if previous_direction is None: return 0.0
    dot = max(-1.0, min(1.0, sum(a*b for a,b in zip(previous_direction, direction))))
    return bias * acos(dot)
