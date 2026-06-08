"""Mesh seam detection utilities for Auto Seam UV Equalizer."""

from __future__ import annotations

from collections import defaultdict
from math import radians
from typing import DefaultDict


MIN_MESH_FACE_COUNT = 1


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
