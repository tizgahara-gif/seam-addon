"""UV island tools for arranging selected UV islands without unwrapping."""

from __future__ import annotations

from collections import defaultdict, deque
from itertools import combinations
from math import ceil, sqrt
from typing import DefaultDict, Iterable

import bmesh
import bpy

EPSILON = 1.0e-6


def _unique_uv_layer_name(mesh, base_name: str) -> str:
    existing_names = {uv_layer.name for uv_layer in mesh.uv_layers}
    candidate = base_name
    suffix = 1
    while candidate in existing_names:
        candidate = f"{base_name}.{suffix:03d}"
        suffix += 1
    return candidate


def _copy_bmesh_uv_loop_data(source_loop_data, target_loop_data) -> None:
    target_loop_data.uv = source_loop_data.uv.copy()
    if hasattr(source_loop_data, "select") and hasattr(target_loop_data, "select"):
        target_loop_data.select = source_loop_data.select
    if hasattr(source_loop_data, "select_edge") and hasattr(target_loop_data, "select_edge"):
        target_loop_data.select_edge = source_loop_data.select_edge
    if hasattr(source_loop_data, "pin_uv") and hasattr(target_loop_data, "pin_uv"):
        target_loop_data.pin_uv = source_loop_data.pin_uv


def _duplicate_active_bmesh_uv_layer(obj, bm, source_layer):
    source_name = obj.data.uv_layers.active.name if obj.data.uv_layers.active else "UVMap"
    duplicate_name = _unique_uv_layer_name(obj.data, f"{source_name}_Grid")
    target_layer = bm.loops.layers.uv.new(duplicate_name)
    bm.loops.layers.uv.active = target_layer

    for face in bm.faces:
        for loop in face.loops:
            _copy_bmesh_uv_loop_data(loop[source_layer], loop[target_layer])

    return target_layer, duplicate_name


def _is_uv_loop_selected(loop, uv_layer) -> bool:
    return bool(getattr(loop[uv_layer], "select", False))


def _uv_points_close(point_a, point_b, tolerance: float = EPSILON) -> bool:
    return (point_a - point_b).length <= tolerance


def _uv_edges_match(loop_a, loop_b, uv_layer) -> bool:
    a_start = loop_a[uv_layer].uv
    a_end = loop_a.link_loop_next[uv_layer].uv
    b_start = loop_b[uv_layer].uv
    b_end = loop_b.link_loop_next[uv_layer].uv

    return (
        _uv_points_close(a_start, b_start) and _uv_points_close(a_end, b_end)
    ) or (
        _uv_points_close(a_start, b_end) and _uv_points_close(a_end, b_start)
    )


def _find_bmesh_uv_face_islands(bm, uv_layer) -> list[list]:
    face_neighbors: DefaultDict[object, set] = defaultdict(set)

    for edge in bm.edges:
        linked_loops = list(edge.link_loops)
        for loop_a, loop_b in combinations(linked_loops, 2):
            if loop_a.face == loop_b.face:
                continue
            if _uv_edges_match(loop_a, loop_b, uv_layer):
                face_neighbors[loop_a.face].add(loop_b.face)
                face_neighbors[loop_b.face].add(loop_a.face)

    islands: list[list] = []
    unvisited = {face for face in bm.faces if not face.hide}

    while unvisited:
        start = unvisited.pop()
        island_faces = [start]
        queue = deque([start])

        while queue:
            face = queue.popleft()
            for neighbor in face_neighbors.get(face, set()):
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    island_faces.append(neighbor)
                    queue.append(neighbor)

        islands.append(island_faces)

    return islands


def _face_island_loops(island_faces: Iterable) -> set:
    island_loops = set()
    for face in island_faces:
        island_loops.update(face.loops)
    return island_loops


def find_selected_uv_islands(obj) -> list[set]:
    """Return selected UV islands as sets of BMesh loops from the active edit UV layer."""
    if obj is None or obj.type != "MESH":
        return []
    if obj.mode != "EDIT":
        raise RuntimeError("Finding selected UV islands requires Edit Mode.")
    if obj.data.uv_layers.active is None:
        raise RuntimeError("Active object has no UV map.")

    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    uv_layer = bm.loops.layers.uv.active
    if uv_layer is None:
        raise RuntimeError("Active object has no UV map.")

    selected_islands = []
    for island_faces in _find_bmesh_uv_face_islands(bm, uv_layer):
        if any(_is_uv_loop_selected(loop, uv_layer) for face in island_faces for loop in face.loops):
            selected_islands.append(_face_island_loops(island_faces))

    return selected_islands


def compute_grid_cells(count: int, layout: str) -> list[tuple[float, float, float, float]]:
    """Compute equal 0-1 UV cells as (min_u, max_u, min_v, max_v)."""
    if count <= 0:
        return []

    if layout == "HORIZONTAL_STRIP":
        columns, rows = count, 1
    elif layout == "VERTICAL_STRIP":
        columns, rows = 1, count
    else:
        columns = ceil(sqrt(count))
        rows = ceil(count / columns)

    cell_width = 1.0 / columns
    cell_height = 1.0 / rows
    cells = []

    for index in range(count):
        column = index % columns
        row = index // columns
        min_u = column * cell_width
        max_u = min_u + cell_width
        max_v = 1.0 - (row * cell_height)
        min_v = max_v - cell_height
        cells.append((min_u, max_u, min_v, max_v))

    return cells


def _uv_bbox(uv_layer, loops: Iterable) -> tuple[float, float, float, float]:
    loop_list = list(loops)
    min_u = min(loop[uv_layer].uv.x for loop in loop_list)
    max_u = max(loop[uv_layer].uv.x for loop in loop_list)
    min_v = min(loop[uv_layer].uv.y for loop in loop_list)
    max_v = max(loop[uv_layer].uv.y for loop in loop_list)
    return min_u, max_u, min_v, max_v


def fit_uv_island_to_cell(mesh, uv_layer, loop_indices, cell: tuple[float, float, float, float], margin: float) -> None:
    """Move and scale one UV island into a grid cell while preserving aspect ratio."""
    del mesh  # Kept for the public helper signature requested by the add-on spec.
    loops = list(loop_indices)
    if not loops:
        return

    min_u, max_u, min_v, max_v = _uv_bbox(uv_layer, loops)
    source_width = max_u - min_u
    source_height = max_v - min_v
    if source_width <= EPSILON or source_height <= EPSILON:
        raise RuntimeError("Selected UV island has a zero-size UV bbox.")

    cell_min_u, cell_max_u, cell_min_v, cell_max_v = cell
    cell_width = cell_max_u - cell_min_u
    cell_height = cell_max_v - cell_min_v
    safe_margin = min(max(margin, 0.0), cell_width * 0.45, cell_height * 0.45)
    target_width = cell_width - (safe_margin * 2.0)
    target_height = cell_height - (safe_margin * 2.0)
    if target_width <= 0.0 or target_height <= 0.0:
        raise RuntimeError("Selected Grid Margin is too large for the selected layout.")

    scale = min(target_width / source_width, target_height / source_height)
    source_center_u = (min_u + max_u) * 0.5
    source_center_v = (min_v + max_v) * 0.5
    target_center_u = cell_min_u + (cell_width * 0.5)
    target_center_v = cell_min_v + (cell_height * 0.5)

    for loop in loops:
        uv = loop[uv_layer].uv
        uv.x = target_center_u + ((uv.x - source_center_u) * scale)
        uv.y = target_center_v + ((uv.y - source_center_v) * scale)


def arrange_selected_uv_islands_to_grid(
    obj,
    margin: float,
    layout: str,
    duplicate_uv_before_arrange: bool,
) -> int:
    """Arrange selected UV islands into equal 0-1 grid cells without unwrapping or packing."""
    if obj is None or obj.type != "MESH":
        return 0
    if obj.mode != "EDIT":
        raise RuntimeError("Arrange Selected UV Islands to Grid requires Edit Mode.")
    if obj.data.uv_layers.active is None:
        raise RuntimeError("Active object has no UV map.")

    try:
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            raise RuntimeError("Active object has no UV map.")

        duplicate_name = None
        if duplicate_uv_before_arrange:
            uv_layer, duplicate_name = _duplicate_active_bmesh_uv_layer(obj, bm, uv_layer)

        selected_islands = find_selected_uv_islands(obj)
        if not selected_islands:
            raise RuntimeError("No selected UV islands were found.")

        selected_islands.sort(key=lambda loops: (-_uv_bbox(uv_layer, loops)[3], _uv_bbox(uv_layer, loops)[0]))
        cells = compute_grid_cells(len(selected_islands), layout)

        for island_loops, cell in zip(selected_islands, cells):
            fit_uv_island_to_cell(mesh, uv_layer, island_loops, cell, margin)

        bmesh.update_edit_mesh(mesh)

        if duplicate_name:
            bpy.ops.object.mode_set(mode="OBJECT")
            mesh.uv_layers.active = mesh.uv_layers[duplicate_name]
            bpy.ops.object.mode_set(mode="EDIT")

        return len(selected_islands)
    except Exception as exc:
        raise RuntimeError(f"Failed to arrange selected UV islands on {obj.name}: {exc}") from exc
