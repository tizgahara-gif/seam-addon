"""Coordinate symmetry matching using a spatial hash (expected O(V + E))."""
from __future__ import annotations

def _cell(co, tolerance): return tuple(round(float(v) / tolerance) for v in co)
def mirrored_coordinate(co, axis):
    result = list(co); result[axis] = -result[axis]; return tuple(result)
def build_unique_vertex_mirror(coordinates, axis=0, tolerance=1e-4):
    buckets = {}
    for index, co in enumerate(coordinates): buckets.setdefault(_cell(co, tolerance), []).append(index)
    mapping, ambiguous = {}, 0
    for index, co in enumerate(coordinates):
        candidates = buckets.get(_cell(mirrored_coordinate(co, axis), tolerance), [])
        candidates = [j for j in candidates if sum((coordinates[j][k]-mirrored_coordinate(co, axis)[k])**2 for k in range(3)) <= tolerance*tolerance]
        if len(candidates) == 1: mapping[index] = candidates[0]
        elif candidates: ambiguous += 1
    return mapping, ambiguous

def build_edge_lookup(edges):
    result = {}
    for i, (a,b) in enumerate(edges): result.setdefault((min(a,b), max(a,b)), []).append(i)
    return result

def mirror_edge_map(coordinates, edges, axis=0, tolerance=1e-4):
    vertices, ambiguous = build_unique_vertex_mirror(coordinates, axis, tolerance)
    lookup, result, skipped = build_edge_lookup(edges), {}, 0
    for i,(a,b) in enumerate(edges):
        if a not in vertices or b not in vertices: skipped += 1; continue
        matches = lookup.get(tuple(sorted((vertices[a], vertices[b]))), [])
        if len(matches) == 1: result[i] = matches[0]
        else: skipped += 1
    return result, skipped + ambiguous
