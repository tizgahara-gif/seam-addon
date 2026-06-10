"""UV creation, unwrap, and equal-region packing helpers."""

from __future__ import annotations

from collections import defaultdict, deque
from math import ceil, sqrt
from typing import DefaultDict

import bpy

from .island_tools import straighten_circular_strip_islands_on_object


def ensure_uv_layer(obj, uv_map_name: str, create_if_missing: bool) -> bool:
    """Activate the named UV map, optionally creating it when missing."""
    if obj is None or obj.type != "MESH":
        return 0

    mesh = obj.data
    uv_layers = mesh.uv_layers
    target_name = uv_map_name.strip() or "UV_Auto"

    if target_name in uv_layers:
        uv_layers.active = uv_layers[target_name]
        return True

    if not create_if_missing:
        return False

    uv_layers.new(name=target_name)
    uv_layers.active = uv_layers[target_name]
    return True


def _switch_to_object_mode() -> None:
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode="OBJECT")


def _select_only_object(obj) -> None:
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _build_edge_to_faces(mesh) -> dict[int, list[int]]:
    edge_to_faces: DefaultDict[int, list[int]] = defaultdict(list)
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            edge_index = mesh.loops[loop_index].edge_index
            edge_to_faces[edge_index].append(polygon.index)
    return dict(edge_to_faces)


def _find_seam_delimited_face_islands(mesh) -> list[list[int]]:
    """Find face islands separated by mesh seam edges."""
    edge_to_faces = _build_edge_to_faces(mesh)
    face_neighbors: DefaultDict[int, set[int]] = defaultdict(set)

    for edge_index, face_indices in edge_to_faces.items():
        if len(face_indices) != 2:
            continue
        if mesh.edges[edge_index].use_seam:
            continue

        face_a, face_b = face_indices
        face_neighbors[face_a].add(face_b)
        face_neighbors[face_b].add(face_a)

    islands: list[list[int]] = []
    unvisited = {polygon.index for polygon in mesh.polygons}

    while unvisited:
        start = unvisited.pop()
        island = [start]
        queue: deque[int] = deque([start])

        while queue:
            face_index = queue.popleft()
            for neighbor in face_neighbors.get(face_index, set()):
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    island.append(neighbor)
                    queue.append(neighbor)

        islands.append(island)

    return islands


def _layout_dimensions(island_count: int, layout: str) -> tuple[int, int]:
    if island_count <= 0:
        return 0, 0

    if layout == "HORIZONTAL_STRIP":
        return island_count, 1

    if layout == "VERTICAL_STRIP":
        return 1, island_count

    columns = ceil(sqrt(island_count))
    rows = ceil(island_count / columns)
    return columns, rows


def _island_loop_indices(mesh, face_indices: list[int]) -> list[int]:
    loop_indices: list[int] = []
    for face_index in face_indices:
        loop_indices.extend(mesh.polygons[face_index].loop_indices)
    return loop_indices


def _uv_bbox(uv_layer, loop_indices: list[int]) -> tuple[float, float, float, float]:
    min_u = min(uv_layer.data[loop_index].uv.x for loop_index in loop_indices)
    max_u = max(uv_layer.data[loop_index].uv.x for loop_index in loop_indices)
    min_v = min(uv_layer.data[loop_index].uv.y for loop_index in loop_indices)
    max_v = max(uv_layer.data[loop_index].uv.y for loop_index in loop_indices)
    return min_u, max_u, min_v, max_v


def equal_region_pack_object(obj, margin: float, layout: str) -> int:
    """Place each seam-delimited UV island into an equal 0-1 UV cell."""
    if obj is None or obj.type != "MESH":
        return 0

    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Equal Region Pack requires an active UV map.")

    islands = _find_seam_delimited_face_islands(mesh)
    if not islands:
        return 0

    columns, rows = _layout_dimensions(len(islands), layout)
    if columns <= 0 or rows <= 0:
        return 0

    cell_width = 1.0 / columns
    cell_height = 1.0 / rows
    safe_margin = min(max(margin, 0.0), cell_width * 0.45, cell_height * 0.45)
    target_width = cell_width - (safe_margin * 2.0)
    target_height = cell_height - (safe_margin * 2.0)

    if target_width <= 0.0 or target_height <= 0.0:
        raise RuntimeError("Equal Region Margin is too large for the selected layout.")

    for island_index, face_indices in enumerate(islands):
        loop_indices = _island_loop_indices(mesh, face_indices)
        if not loop_indices:
            continue

        min_u, max_u, min_v, max_v = _uv_bbox(uv_layer, loop_indices)
        source_width = max_u - min_u
        source_height = max_v - min_v

        if source_width <= 1.0e-8 or source_height <= 1.0e-8:
            raise RuntimeError(f"Equal Region Pack found a zero-size UV island at index {island_index}.")

        scale = min(target_width / source_width, target_height / source_height)
        source_center_u = (min_u + max_u) * 0.5
        source_center_v = (min_v + max_v) * 0.5

        column = island_index % columns
        row = island_index // columns
        cell_min_u = column * cell_width
        cell_min_v = 1.0 - ((row + 1) * cell_height)
        target_center_u = cell_min_u + (cell_width * 0.5)
        target_center_v = cell_min_v + (cell_height * 0.5)

        for loop_index in loop_indices:
            uv = uv_layer.data[loop_index].uv
            uv.x = target_center_u + ((uv.x - source_center_u) * scale)
            uv.y = target_center_v + ((uv.y - source_center_v) * scale)

    mesh.update()
    return len(islands)


def unwrap_object(
    obj,
    uv_map_name: str,
    create_if_missing: bool,
    method: str,
    margin: float,
    average_islands: bool,
    pack_islands: bool,
    straighten_circular_strip_islands: bool,
    circular_strip_min_faces: int,
    circular_strip_margin: float,
    equal_region_pack: bool,
    equal_region_margin: float,
    equal_region_layout: str,
) -> int:
    """Unwrap one mesh object using the currently marked seams."""
    if obj is None or obj.type != "MESH":
        return 0

    try:
        _switch_to_object_mode()
        _select_only_object(obj)

        if not ensure_uv_layer(obj, uv_map_name, create_if_missing):
            raise RuntimeError(f"UV map '{uv_map_name}' does not exist and Create UV If Missing is disabled.")

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.unwrap(method=method, margin=margin)

        straightened_count = 0
        if straighten_circular_strip_islands:
            bpy.ops.object.mode_set(mode="OBJECT")
            straightened_count = straighten_circular_strip_islands_on_object(
                obj,
                circular_strip_min_faces,
                circular_strip_margin,
            )
            bpy.ops.object.mode_set(mode="EDIT")

        if average_islands:
            bpy.ops.uv.average_islands_scale()

        if equal_region_pack:
            bpy.ops.object.mode_set(mode="OBJECT")
            equal_region_pack_object(obj, equal_region_margin, equal_region_layout)
        elif pack_islands:
            bpy.ops.uv.pack_islands(margin=margin)

        bpy.ops.object.mode_set(mode="OBJECT")
        return straightened_count
    except Exception as exc:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        raise RuntimeError(f"Failed to unwrap {obj.name}: {exc}") from exc



def unwrap_object_pack(
    obj,
    uv_map_name: str,
    create_if_missing: bool,
    method: str,
    margin: float,
    average_islands: bool,
    straighten_circular_strip_islands: bool,
    circular_strip_min_faces: int,
    circular_strip_margin: float,
) -> int:
    """Unwrap one mesh object and always pack islands with Blender Pack Islands."""
    if obj is None or obj.type != "MESH":
        return 0

    try:
        _switch_to_object_mode()
        _select_only_object(obj)

        if not ensure_uv_layer(obj, uv_map_name, create_if_missing):
            raise RuntimeError(f"UV map '{uv_map_name}' does not exist and Create UV If Missing is disabled.")

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.unwrap(method=method, margin=margin)

        straightened_count = 0
        if straighten_circular_strip_islands:
            bpy.ops.object.mode_set(mode="OBJECT")
            straightened_count = straighten_circular_strip_islands_on_object(
                obj,
                circular_strip_min_faces,
                circular_strip_margin,
            )
            bpy.ops.object.mode_set(mode="EDIT")

        if average_islands:
            bpy.ops.uv.average_islands_scale()

        bpy.ops.uv.pack_islands(margin=margin)

        bpy.ops.object.mode_set(mode="OBJECT")
        return straightened_count
    except Exception as exc:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        raise RuntimeError(f"Failed to pack unwrap {obj.name}: {exc}") from exc
