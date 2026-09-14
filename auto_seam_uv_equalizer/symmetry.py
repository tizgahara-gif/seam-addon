"""Linear-time symmetry matching and validation-first UV transfer planning.

All geometry is evaluated in object-local space; no object transform or mesh
topology is modified.  The pure helpers are deliberately importable by pytest
without Blender.
"""
from __future__ import annotations

from itertools import product
from math import floor, isfinite
from typing import NamedTuple


class SymmetryError(ValueError):
    """A safe, user-facing symmetry validation failure."""


class SymmetryPlan(NamedTuple):
    vertex_pairs: dict[int, int]
    edge_pairs: dict[int, int]
    face_pairs: dict[int, int]
    loop_pairs: tuple[tuple[int, int], ...]
    source_faces: tuple[int, ...]


def _cell(co, tolerance):
    return tuple(floor(float(value) / tolerance) for value in co)


def mirrored_coordinate(co, axis):
    result = list(co)
    result[axis] = -result[axis]
    return tuple(result)


def build_unique_vertex_mirror(coordinates, axis=0, tolerance=1e-4):
    """Return unique mirror pairs and ambiguous count, checking 27 cells."""
    if tolerance <= 0:
        raise ValueError("tolerance must be positive")
    buckets = {}
    for index, co in enumerate(coordinates):
        buckets.setdefault(_cell(co, tolerance), []).append(index)
    mapping, ambiguous = {}, 0
    offsets = tuple(product((-1, 0, 1), repeat=3))
    tolerance_squared = tolerance * tolerance
    for index, co in enumerate(coordinates):
        if abs(float(co[axis])) <= tolerance:
            mapping[index] = index
            continue
        target = mirrored_coordinate(co, axis)
        cell = _cell(target, tolerance)
        candidates = []
        for offset in offsets:
            candidates.extend(buckets.get(tuple(cell[i] + offset[i] for i in range(3)), ()))
        candidates = [candidate for candidate in candidates if sum(
            (float(coordinates[candidate][i]) - target[i]) ** 2 for i in range(3)
        ) <= tolerance_squared]
        if len(candidates) == 1:
            mapping[index] = candidates[0]
        elif len(candidates) > 1:
            ambiguous += 1
    return mapping, ambiguous


def build_edge_lookup(edges):
    result = {}
    for index, (a, b) in enumerate(edges):
        result.setdefault(tuple(sorted((a, b))), []).append(index)
    return result


def mirror_edge_map(coordinates, edges, axis=0, tolerance=1e-4):
    vertices, ambiguous = build_unique_vertex_mirror(coordinates, axis, tolerance)
    lookup, result, skipped = build_edge_lookup(edges), {}, 0
    for index, (a, b) in enumerate(edges):
        if a not in vertices or b not in vertices:
            skipped += 1
            continue
        matches = lookup.get(tuple(sorted((vertices[a], vertices[b]))), ())
        if len(matches) == 1:
            result[index] = matches[0]
        else:
            skipped += 1
    return result, skipped + ambiguous


def build_symmetry_plan(coordinates, edges, faces, source_faces, axis=0,
                        source_sign=-1, tolerance=1e-4):
    """Validate every pair and return loop-index pairs without changing UVs."""
    vertex_pairs, ambiguous = build_unique_vertex_mirror(coordinates, axis, tolerance)
    source_faces = tuple(source_faces)
    if not source_faces:
        raise SymmetryError("no source-side faces in the selected scope")

    needed_vertices = {vertex for face_index in source_faces for vertex in faces[face_index]}
    missing = needed_vertices - vertex_pairs.keys()
    if ambiguous:
        # Ambiguity anywhere in the requested faces cannot be distinguished
        # from an unmatched entry in the compact mapping.
        ambiguous_vertices = [v for v in needed_vertices if v not in vertex_pairs]
        if ambiguous_vertices:
            raise SymmetryError(f"ambiguous or unmatched vertex: {ambiguous_vertices[0]}")
    if missing:
        raise SymmetryError(f"unmatched vertex: {min(missing)}")

    edge_lookup = build_edge_lookup(edges)
    face_lookup = {}
    for index, face in enumerate(faces):
        face_lookup.setdefault(frozenset(face), []).append(index)

    edge_pairs, face_pairs, loop_pairs = {}, {}, []
    loop_starts, cursor = [], 0
    for face in faces:
        loop_starts.append(cursor)
        cursor += len(face)

    for source_face in source_faces:
        face = faces[source_face]
        sides = [float(coordinates[v][axis]) * source_sign for v in face]
        if not any(value > tolerance for value in sides):
            raise SymmetryError(f"face {source_face} is not on the source side")
        if any(value < -tolerance for value in sides):
            raise SymmetryError(f"face {source_face} crosses the symmetry plane")
        mirrored = tuple(vertex_pairs[v] for v in face)
        matches = face_lookup.get(frozenset(mirrored), ())
        if len(matches) != 1 or matches[0] == source_face:
            reason = "ambiguous" if len(matches) > 1 else "missing"
            raise SymmetryError(f"{reason} mirrored face for face {source_face}")
        destination_face = matches[0]
        face_pairs[source_face] = destination_face
        destination_loops = {vertex: loop_starts[destination_face] + offset
                             for offset, vertex in enumerate(faces[destination_face])}
        for offset, vertex in enumerate(face):
            target_vertex = vertex_pairs[vertex]
            if target_vertex not in destination_loops:
                raise SymmetryError(f"missing destination loop for vertex {vertex}")
            loop_pairs.append((loop_starts[source_face] + offset,
                               destination_loops[target_vertex]))
        for offset, a in enumerate(face):
            b = face[(offset + 1) % len(face)]
            source_edges = edge_lookup.get(tuple(sorted((a, b))), ())
            target_edges = edge_lookup.get(tuple(sorted((vertex_pairs[a], vertex_pairs[b]))), ())
            if len(source_edges) != 1 or len(target_edges) != 1:
                raise SymmetryError(f"ambiguous or missing edge on face {source_face}")
            edge_pairs[source_edges[0]] = target_edges[0]
    return SymmetryPlan(vertex_pairs, edge_pairs, face_pairs, tuple(loop_pairs), source_faces)


def transferred_uvs(source_uvs, loop_pairs, layout="OVERLAP", island_gap=0.02):
    """Build destination writes in memory; callers commit only after success."""
    values = [(source_loop, destination_loop, tuple(source_uvs[source_loop]))
              for source_loop, destination_loop in loop_pairs]
    if layout == "OVERLAP":
        return {destination: uv for _, destination, uv in values}
    if layout != "SEPARATE_MIRRORED":
        raise SymmetryError(f"unknown UV layout: {layout}")
    if not values:
        raise SymmetryError("no UV loops to transfer")
    minimum_u = min(uv[0] for _, _, uv in values)
    maximum_u = max(uv[0] for _, _, uv in values)
    # Reflect about the source bounds, then translate one gap-width to the right.
    offset = (maximum_u - minimum_u) + island_gap
    return {destination: (minimum_u + maximum_u - uv[0] + offset, uv[1])
            for _, destination, uv in values}


def exact_texture_x_uvs(source_uvs, loop_pairs, source_side="LEFT_HALF", epsilon=1e-7):
    """Validate and plan an exact reflection about U=0.5 without mutating UVs."""
    if epsilon < 0:
        raise ValueError("epsilon must not be negative")
    if source_side not in {"LEFT_HALF", "RIGHT_HALF"}:
        raise SymmetryError(f"unknown texture source side: {source_side}")
    if not loop_pairs:
        raise SymmetryError("no UV loop pairs to transfer")

    source_loops = [source for source, _destination in loop_pairs]
    destination_loops = [destination for _source, destination in loop_pairs]
    if (len(set(source_loops)) != len(source_loops)
            or len(set(destination_loops)) != len(destination_loops)
            or set(source_loops) & set(destination_loops)):
        raise SymmetryError("source/destination loop duplication error")

    writes = {}
    for source, destination in loop_pairs:
        if (not isinstance(source, int) or not isinstance(destination, int)
                or source < 0 or destination < 0
                or source >= len(source_uvs) or destination >= len(source_uvs)):
            raise SymmetryError("loop pair is incomplete or out of range")
        try:
            u, v = (float(value) for value in source_uvs[source][:2])
        except (IndexError, TypeError, ValueError) as exc:
            raise SymmetryError(f"invalid source UV loop: {source}") from exc
        if not isfinite(u) or not isfinite(v):
            raise SymmetryError("Source UVs are outside the 0-1 UV space.")
        if not (-epsilon <= u <= 1.0 + epsilon
                and -epsilon <= v <= 1.0 + epsilon):
            raise SymmetryError("Source UVs are outside the 0-1 UV space.")
        if source_side == "LEFT_HALF" and not -epsilon <= u <= 0.5 + epsilon:
            raise SymmetryError(
                "Source UVs are not fully contained in the selected texture half.")
        if source_side == "RIGHT_HALF" and not 0.5 - epsilon <= u <= 1.0 + epsilon:
            raise SymmetryError(
                "Source UVs are not fully contained in the selected texture half.")
        destination_uv = (1.0 - u, v)
        if not (-epsilon <= destination_uv[0] <= 1.0 + epsilon
                and -epsilon <= destination_uv[1] <= 1.0 + epsilon):
            raise SymmetryError("Destination UVs would be outside the 0-1 UV space.")
        writes[destination] = destination_uv
    return writes
