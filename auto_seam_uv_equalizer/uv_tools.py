"""UV creation, unwrap, and equal-region packing helpers."""

from __future__ import annotations

from collections import defaultdict, deque
from itertools import combinations
from math import ceil, sqrt
from typing import DefaultDict

import bmesh
import bpy


def ensure_uv_layer(obj, uv_map_name: str, create_if_missing: bool) -> bool:
    """Activate the named UV map, optionally creating it when missing."""
    if obj is None or obj.type != "MESH":
        return False

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
    loop_data = loop[uv_layer]
    return bool(getattr(loop_data, "select", False))


def _uv_points_close(point_a, point_b, tolerance: float = 1.0e-6) -> bool:
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


def _find_bmesh_uv_islands(bm, uv_layer) -> list[list]:
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


def _bmesh_island_loop_data(island_faces: list, uv_layer) -> list:
    loop_data = []
    for face in island_faces:
        for loop in face.loops:
            loop_data.append(loop[uv_layer])
    return loop_data


def _bmesh_uv_bbox(loop_data: list) -> tuple[float, float, float, float]:
    min_u = min(data.uv.x for data in loop_data)
    max_u = max(data.uv.x for data in loop_data)
    min_v = min(data.uv.y for data in loop_data)
    max_v = max(data.uv.y for data in loop_data)
    return min_u, max_u, min_v, max_v


def _arrange_bmesh_uv_islands(islands: list[list], uv_layer, margin: float, layout: str) -> int:
    island_loop_data = [_bmesh_island_loop_data(island_faces, uv_layer) for island_faces in islands]
    island_loop_data = [loop_data for loop_data in island_loop_data if loop_data]

    island_loop_data.sort(key=lambda loop_data: (-_bmesh_uv_bbox(loop_data)[3], _bmesh_uv_bbox(loop_data)[0]))

    columns, rows = _layout_dimensions(len(island_loop_data), layout)
    if columns <= 0 or rows <= 0:
        return 0

    cell_width = 1.0 / columns
    cell_height = 1.0 / rows
    safe_margin = min(max(margin, 0.0), cell_width * 0.45, cell_height * 0.45)
    target_width = cell_width - (safe_margin * 2.0)
    target_height = cell_height - (safe_margin * 2.0)

    if target_width <= 0.0 or target_height <= 0.0:
        raise RuntimeError("Selected UV grid margin is too large for the selected layout.")

    for island_index, loop_data in enumerate(island_loop_data):
        min_u, max_u, min_v, max_v = _bmesh_uv_bbox(loop_data)
        source_width = max_u - min_u
        source_height = max_v - min_v

        if source_width <= 1.0e-8 or source_height <= 1.0e-8:
            raise RuntimeError(f"Selected UV island at index {island_index} has a zero-size UV bbox.")

        scale = min(target_width / source_width, target_height / source_height)
        source_center_u = (min_u + max_u) * 0.5
        source_center_v = (min_v + max_v) * 0.5

        column = island_index % columns
        row = island_index // columns
        cell_min_u = column * cell_width
        cell_min_v = 1.0 - ((row + 1) * cell_height)
        target_center_u = cell_min_u + (cell_width * 0.5)
        target_center_v = cell_min_v + (cell_height * 0.5)

        for data in loop_data:
            data.uv.x = target_center_u + ((data.uv.x - source_center_u) * scale)
            data.uv.y = target_center_v + ((data.uv.y - source_center_v) * scale)

    return len(island_loop_data)


def arrange_selected_uv_islands_to_grid(
    obj,
    margin: float,
    layout: str,
    duplicate_uv_before_arrange: bool,
) -> int:
    """Arrange selected UV islands into equal 0-1 grid cells without unwrapping."""
    if obj is None or obj.type != "MESH":
        return 0
    if obj.mode != "EDIT":
        raise RuntimeError("Arrange Selected UV Islands to Grid requires Edit Mode.")
    if obj.data.uv_layers.active is None:
        raise RuntimeError("Arrange Selected UV Islands to Grid requires an active UV map.")

    try:
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            raise RuntimeError("Arrange Selected UV Islands to Grid requires an active UV map.")

        duplicate_name = None
        if duplicate_uv_before_arrange:
            uv_layer, duplicate_name = _duplicate_active_bmesh_uv_layer(obj, bm, uv_layer)

        islands = _find_bmesh_uv_islands(bm, uv_layer)
        selected_islands = [
            island_faces
            for island_faces in islands
            if any(_is_uv_loop_selected(loop, uv_layer) for face in island_faces for loop in face.loops)
        ]

        if not selected_islands:
            raise RuntimeError("No selected UV islands were found.")

        arranged_count = _arrange_bmesh_uv_islands(selected_islands, uv_layer, margin, layout)
        bmesh.update_edit_mesh(mesh)

        if duplicate_name:
            bpy.ops.object.mode_set(mode="OBJECT")
            mesh.uv_layers.active = mesh.uv_layers[duplicate_name]
            bpy.ops.object.mode_set(mode="EDIT")

        return arranged_count
    except Exception as exc:
        raise RuntimeError(f"Failed to arrange selected UV islands on {obj.name}: {exc}") from exc


def unwrap_object(
    obj,
    uv_map_name: str,
    create_if_missing: bool,
    method: str,
    margin: float,
    average_islands: bool,
    pack_islands: bool,
    equal_region_pack: bool,
    equal_region_margin: float,
    equal_region_layout: str,
) -> bool:
    """Unwrap one mesh object using the currently marked seams."""
    if obj is None or obj.type != "MESH":
        return False

    try:
        _switch_to_object_mode()
        _select_only_object(obj)

        if not ensure_uv_layer(obj, uv_map_name, create_if_missing):
            raise RuntimeError(f"UV map '{uv_map_name}' does not exist and Create UV If Missing is disabled.")

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.unwrap(method=method, margin=margin)

        if average_islands:
            bpy.ops.uv.average_islands_scale()

        if equal_region_pack:
            bpy.ops.object.mode_set(mode="OBJECT")
            equal_region_pack_object(obj, equal_region_margin, equal_region_layout)
        elif pack_islands:
            bpy.ops.uv.pack_islands(margin=margin)

        bpy.ops.object.mode_set(mode="OBJECT")
        return True
    except Exception as exc:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        raise RuntimeError(f"Failed to unwrap {obj.name}: {exc}") from exc
