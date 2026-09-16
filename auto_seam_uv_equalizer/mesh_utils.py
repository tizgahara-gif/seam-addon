"""Shared, linear-time mesh topology indexes."""

from __future__ import annotations

from collections import defaultdict


def selected_visible_mesh_objects(context):
    """Return the selected, visible mesh objects targeted by public workflows."""
    return [
        obj
        for obj in context.selected_objects
        if obj.type == "MESH" and obj.visible_get(view_layer=context.view_layer)
    ]


def build_mesh_topology(mesh):
    """Return reusable edge/loop/face lookup tables for ``mesh``.

    Building these tables once avoids repeatedly scanning every polygon for a
    loop or edge owner in island and seam operations.
    """
    edge_to_polygon_loops = defaultdict(list)
    loop_to_face = {}
    loop_to_next = {}

    for polygon in mesh.polygons:
        loops = list(polygon.loop_indices)
        for offset, loop_index in enumerate(loops):
            loop_to_face[loop_index] = polygon.index
            loop_to_next[loop_index] = loops[(offset + 1) % len(loops)]
            edge_index = mesh.loops[loop_index].edge_index
            edge_to_polygon_loops[edge_index].append((polygon.index, loop_index))

    edge_to_faces = {
        edge_index: [face_index for face_index, _loop_index in linked]
        for edge_index, linked in edge_to_polygon_loops.items()
    }
    return edge_to_faces, dict(edge_to_polygon_loops), loop_to_face, loop_to_next


def build_edge_to_faces(mesh) -> dict[int, list[int]]:
    """Return mesh edge indices mapped to their connected polygon indices."""
    return build_mesh_topology(mesh)[0]
