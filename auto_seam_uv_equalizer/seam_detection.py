"""Mesh seam detection utilities for Auto Seam UV Equalizer."""

from __future__ import annotations

from collections import defaultdict, deque
from math import radians
from typing import DefaultDict


MIN_MESH_FACE_COUNT = 1
LONGITUDINAL_ALIGNMENT = 0.65
LONGITUDINAL_SIDE_TOLERANCE = 0.18


def clear_seams(mesh) -> int:
    """Clear all seam flags on a mesh and return the number of changed edges."""
    cleared_count = 0
    for edge in mesh.edges:
        if edge.use_seam:
            edge.use_seam = False
            cleared_count += 1
    mesh.update()
    return cleared_count


def build_edge_to_faces(mesh) -> dict[int, list[int]]:
    """Build a mapping from mesh edge index to connected polygon indices."""
    edge_to_faces: DefaultDict[int, list[int]] = defaultdict(list)

    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            edge_index = mesh.loops[loop_index].edge_index
            edge_to_faces[edge_index].append(polygon.index)

    return dict(edge_to_faces)


def _should_mark_two_face_edge(mesh, face_indices: list[int], threshold_radians: float, use_material_boundary: bool) -> bool:
    face_a = mesh.polygons[face_indices[0]]
    face_b = mesh.polygons[face_indices[1]]

    if face_a.normal.angle(face_b.normal) >= threshold_radians:
        return True

    if use_material_boundary and face_a.material_index != face_b.material_index:
        return True

    return False


def mark_auto_seams(
    obj,
    angle_threshold_degrees: float,
    use_material_boundary: bool,
    use_boundary_edges: bool,
    use_non_manifold_edges: bool,
) -> int:
    """Mark automatic seams on a mesh object and return the number of newly marked edges."""
    if obj is None or obj.type != "MESH":
        return 0

    mesh = obj.data
    mesh.update(calc_edges=True)

    if len(mesh.polygons) < MIN_MESH_FACE_COUNT:
        return 0

    threshold_radians = radians(angle_threshold_degrees)
    edge_to_faces = build_edge_to_faces(mesh)
    marked_count = 0

    for edge in mesh.edges:
        face_indices = edge_to_faces.get(edge.index, [])
        face_count = len(face_indices)
        should_mark = False

        if face_count == 1:
            should_mark = use_boundary_edges
        elif face_count == 2:
            should_mark = _should_mark_two_face_edge(
                mesh,
                face_indices,
                threshold_radians,
                use_material_boundary,
            )
        elif face_count > 2:
            should_mark = use_non_manifold_edges

        if should_mark and not edge.use_seam:
            edge.use_seam = True
            marked_count += 1

    mesh.update()
    return marked_count


def _longest_bbox_axis(mesh) -> tuple[int, list[float], list[float]] | None:
    if not mesh.vertices:
        return None

    mins = [min(vertex.co[i] for vertex in mesh.vertices) for i in range(3)]
    maxs = [max(vertex.co[i] for vertex in mesh.vertices) for i in range(3)]
    extents = [maxs[i] - mins[i] for i in range(3)]
    longest_axis = max(range(3), key=lambda index: extents[index])

    if extents[longest_axis] <= 1.0e-6:
        return None

    return longest_axis, mins, extents


def _edge_axis_alignment(mesh, edge, axis: int) -> float:
    vert_a = mesh.vertices[edge.vertices[0]].co
    vert_b = mesh.vertices[edge.vertices[1]].co
    direction = vert_b - vert_a

    if direction.length <= 1.0e-6:
        return 0.0

    return abs(direction.normalized()[axis])


def _edge_side_score(mesh, edge, minor_axes: list[int], mins: list[float], extents: list[float]) -> float:
    midpoint = (mesh.vertices[edge.vertices[0]].co + mesh.vertices[edge.vertices[1]].co) * 0.5
    score = 0.0

    for axis in minor_axes:
        extent = extents[axis]
        if extent > 1.0e-6:
            score += (midpoint[axis] - mins[axis]) / extent

    return score


def _find_longitudinal_candidates(mesh, edge_to_faces: dict[int, list[int]], axis: int) -> list[int]:
    candidates = []
    for edge in mesh.edges:
        if edge.use_seam:
            continue
        if len(edge_to_faces.get(edge.index, [])) != 2:
            continue
        if _edge_axis_alignment(mesh, edge, axis) >= LONGITUDINAL_ALIGNMENT:
            candidates.append(edge.index)
    return candidates


def _has_existing_longitudinal_seam(mesh, edge_to_faces: dict[int, list[int]], axis: int) -> bool:
    for edge in mesh.edges:
        if not edge.use_seam:
            continue
        if len(edge_to_faces.get(edge.index, [])) != 2:
            continue
        if _edge_axis_alignment(mesh, edge, axis) >= LONGITUDINAL_ALIGNMENT:
            return True
    return False


def _collect_connected_edge_strip(mesh, candidate_indices: set[int], seed_index: int, seed_score: float, minor_axes: list[int], mins: list[float], extents: list[float]) -> set[int]:
    vertex_to_edges: DefaultDict[int, list[int]] = defaultdict(list)
    for edge_index in candidate_indices:
        edge = mesh.edges[edge_index]
        vertex_to_edges[edge.vertices[0]].append(edge_index)
        vertex_to_edges[edge.vertices[1]].append(edge_index)

    strip = set()
    queue: deque[int] = deque([seed_index])

    while queue:
        edge_index = queue.popleft()
        if edge_index in strip:
            continue

        edge = mesh.edges[edge_index]
        score = _edge_side_score(mesh, edge, minor_axes, mins, extents)
        if abs(score - seed_score) > LONGITUDINAL_SIDE_TOLERANCE:
            continue

        strip.add(edge_index)
        for vertex_index in edge.vertices:
            for next_edge_index in vertex_to_edges[vertex_index]:
                if next_edge_index not in strip:
                    queue.append(next_edge_index)

    return strip


def mark_longitudinal_seam_helper(obj) -> int:
    """Heuristically add one lengthwise seam strip for cylindrical or cable-like meshes."""
    if obj is None or obj.type != "MESH":
        return 0

    mesh = obj.data
    mesh.update(calc_edges=True)

    if len(mesh.edges) == 0 or len(mesh.polygons) < MIN_MESH_FACE_COUNT:
        return 0

    bbox_data = _longest_bbox_axis(mesh)
    if bbox_data is None:
        return 0

    axis, mins, extents = bbox_data
    edge_to_faces = build_edge_to_faces(mesh)

    if _has_existing_longitudinal_seam(mesh, edge_to_faces, axis):
        return 0

    candidates = _find_longitudinal_candidates(mesh, edge_to_faces, axis)
    if not candidates:
        return 0

    minor_axes = [index for index in range(3) if index != axis]
    seed_index = min(
        candidates,
        key=lambda edge_index: _edge_side_score(mesh, mesh.edges[edge_index], minor_axes, mins, extents),
    )
    seed_score = _edge_side_score(mesh, mesh.edges[seed_index], minor_axes, mins, extents)
    strip = _collect_connected_edge_strip(mesh, set(candidates), seed_index, seed_score, minor_axes, mins, extents)

    marked_count = 0
    for edge_index in strip:
        edge = mesh.edges[edge_index]
        if not edge.use_seam:
            edge.use_seam = True
            marked_count += 1

    mesh.update()
    return marked_count
