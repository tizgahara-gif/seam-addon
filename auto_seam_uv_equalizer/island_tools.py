"""UV island tools for unwrap post-processing."""

from __future__ import annotations

from collections import defaultdict, deque
from itertools import combinations
from typing import DefaultDict, Iterable


EPSILON = 1.0e-6
MAX_CIRCULAR_STRIP_ASPECT = 100.0



def _uv_points_close(point_a, point_b, tolerance: float = EPSILON) -> bool:
    return (point_a - point_b).length <= tolerance


def _mesh_loop_uv_edge(mesh, uv_layer, loop_index: int) -> tuple:
    polygon = next(polygon for polygon in mesh.polygons if polygon.loop_start <= loop_index < polygon.loop_start + polygon.loop_total)
    offset = loop_index - polygon.loop_start
    next_loop_index = polygon.loop_start + ((offset + 1) % polygon.loop_total)
    return uv_layer.data[loop_index].uv, uv_layer.data[next_loop_index].uv


def _mesh_uv_edges_match(mesh, uv_layer, loop_a_index: int, loop_b_index: int) -> bool:
    a_start, a_end = _mesh_loop_uv_edge(mesh, uv_layer, loop_a_index)
    b_start, b_end = _mesh_loop_uv_edge(mesh, uv_layer, loop_b_index)
    return (
        _uv_points_close(a_start, b_start) and _uv_points_close(a_end, b_end)
    ) or (
        _uv_points_close(a_start, b_end) and _uv_points_close(a_end, b_start)
    )


def _mesh_edge_to_polygon_loops(mesh) -> dict[int, list[tuple[int, int]]]:
    edge_to_loops: DefaultDict[int, list[tuple[int, int]]] = defaultdict(list)
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            edge_to_loops[mesh.loops[loop_index].edge_index].append((polygon.index, loop_index))
    return dict(edge_to_loops)


def find_uv_islands(obj) -> list[set[int]]:
    """Find UV islands on the active UV map and return them as mesh loop-index sets."""
    if obj is None or obj.type != "MESH":
        return []

    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Active object has no UV map.")

    face_neighbors: DefaultDict[int, set[int]] = defaultdict(set)
    for linked_loops in _mesh_edge_to_polygon_loops(mesh).values():
        for (face_a, loop_a_index), (face_b, loop_b_index) in combinations(linked_loops, 2):
            if face_a == face_b:
                continue
            if _mesh_uv_edges_match(mesh, uv_layer, loop_a_index, loop_b_index):
                face_neighbors[face_a].add(face_b)
                face_neighbors[face_b].add(face_a)

    islands: list[set[int]] = []
    unvisited = {polygon.index for polygon in mesh.polygons}

    while unvisited:
        start = unvisited.pop()
        island_faces = [start]
        queue = deque([start])

        while queue:
            face_index = queue.popleft()
            for neighbor in face_neighbors.get(face_index, set()):
                if neighbor in unvisited:
                    unvisited.remove(neighbor)
                    island_faces.append(neighbor)
                    queue.append(neighbor)

        loop_indices = set()
        for face_index in island_faces:
            loop_indices.update(mesh.polygons[face_index].loop_indices)
        islands.append(loop_indices)

    return islands


def _loop_face_count(mesh, loop_indices: Iterable[int]) -> int:
    face_indices = set()
    for loop_index in loop_indices:
        for polygon in mesh.polygons:
            if polygon.loop_start <= loop_index < polygon.loop_start + polygon.loop_total:
                face_indices.add(polygon.index)
                break
    return len(face_indices)


def _normalized_angle_from_start(angle: float, start_angle: float) -> float:
    from math import tau

    value = angle - start_angle
    while value < 0.0:
        value += tau
    while value >= tau:
        value -= tau
    return value


def _circular_strip_parameters(mesh, uv_layer, loop_indices: Iterable[int], min_faces: int):
    from math import atan2, pi, tau

    loop_list = list(loop_indices)
    if _loop_face_count(mesh, loop_list) < min_faces or len(loop_list) < 6:
        return None

    coords = [uv_layer.data[loop_index].uv.copy() for loop_index in loop_list]
    center_u = sum(coord.x for coord in coords) / len(coords)
    center_v = sum(coord.y for coord in coords) / len(coords)
    polar = []

    for coord in coords:
        delta_u = coord.x - center_u
        delta_v = coord.y - center_v
        radius = (delta_u * delta_u + delta_v * delta_v) ** 0.5
        angle = atan2(delta_v, delta_u)
        if angle < 0.0:
            angle += tau
        polar.append((angle, radius))

    radii = [radius for _, radius in polar]
    min_radius = min(radii)
    max_radius = max(radii)
    radius_range = max_radius - min_radius
    mean_radius = sum(radii) / len(radii)
    min_u = min(coord.x for coord in coords)
    max_u = max(coord.x for coord in coords)
    min_v = min(coord.y for coord in coords)
    max_v = max(coord.y for coord in coords)
    bbox_diagonal = (((max_u - min_u) ** 2) + ((max_v - min_v) ** 2)) ** 0.5

    if mean_radius <= EPSILON or radius_range <= max(EPSILON, bbox_diagonal * 0.02):
        return None

    sorted_angles = sorted(angle for angle, _ in polar)
    gaps = []
    for index, angle in enumerate(sorted_angles):
        next_angle = sorted_angles[(index + 1) % len(sorted_angles)]
        if index == len(sorted_angles) - 1:
            next_angle += tau
        gaps.append((next_angle - angle, index))

    max_gap, gap_index = max(gaps, key=lambda item: item[0])
    start_angle = sorted_angles[(gap_index + 1) % len(sorted_angles)]
    unwrapped_angles = [_normalized_angle_from_start(angle, start_angle) for angle, _ in polar]
    angle_range = max(unwrapped_angles) - min(unwrapped_angles)

    if angle_range < (pi * 0.5):
        return None
    if max_gap > (tau * 0.85):
        return None

    return {
        "center": (center_u, center_v),
        "start_angle": start_angle,
        "angle_range": angle_range,
        "min_radius": min_radius,
        "mean_radius": mean_radius,
        "radius_range": radius_range,
        "bbox": (min_u, max_u, min_v, max_v),
    }


def straighten_circular_strip_island(mesh, uv_layer, loop_indices, margin: float) -> bool:
    """Straighten one circular or arc-shaped UV island into a horizontal strip."""
    parameters = _circular_strip_parameters(mesh, uv_layer, loop_indices, min_faces=3)
    if parameters is None:
        return False

    min_u, max_u, min_v, max_v = parameters["bbox"]
    bbox_width = max_u - min_u
    bbox_height = max_v - min_v
    safe_margin = min(max(margin, 0.0), bbox_width * 0.45, bbox_height * 0.45)
    available_width = bbox_width - (safe_margin * 2.0)
    available_height = bbox_height - (safe_margin * 2.0)
    if available_width <= EPSILON or available_height <= EPSILON:
        return False

    arc_length = parameters["mean_radius"] * parameters["angle_range"]
    strip_thickness = parameters["radius_range"]
    if strip_thickness <= EPSILON:
        return False

    target_aspect = arc_length / strip_thickness
    if target_aspect <= EPSILON or target_aspect > MAX_CIRCULAR_STRIP_ASPECT:
        return False

    target_width = available_width
    target_height = target_width / target_aspect
    if target_height > available_height:
        target_height = available_height
        target_width = target_height * target_aspect
    if target_width <= EPSILON or target_height <= EPSILON:
        return False

    bbox_center_u = (min_u + max_u) * 0.5
    bbox_center_v = (min_v + max_v) * 0.5
    target_min_u = bbox_center_u - (target_width * 0.5)
    target_min_v = bbox_center_v - (target_height * 0.5)

    from math import atan2, tau

    center_u, center_v = parameters["center"]
    for loop_index in loop_indices:
        uv = uv_layer.data[loop_index].uv
        delta_u = uv.x - center_u
        delta_v = uv.y - center_v
        radius = (delta_u * delta_u + delta_v * delta_v) ** 0.5
        angle = atan2(delta_v, delta_u)
        if angle < 0.0:
            angle += tau
        strip_u = _normalized_angle_from_start(angle, parameters["start_angle"]) / parameters["angle_range"]
        strip_v = (radius - parameters["min_radius"]) / parameters["radius_range"]
        uv.x = target_min_u + (max(0.0, min(1.0, strip_u)) * target_width)
        uv.y = target_min_v + (max(0.0, min(1.0, strip_v)) * target_height)

    return True


def straighten_circular_strip_islands_on_object(obj, min_faces: int, margin: float) -> int:
    """Straighten circular or arc-shaped UV strip islands on the active UV map."""
    if obj is None or obj.type != "MESH":
        return 0

    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Active object has no UV map.")

    straightened_count = 0
    for loop_indices in find_uv_islands(obj):
        try:
            if _loop_face_count(mesh, loop_indices) < min_faces:
                continue
            if straighten_circular_strip_island(mesh, uv_layer, loop_indices, margin):
                straightened_count += 1
        except Exception:
            continue

    if straightened_count:
        mesh.update()

    return straightened_count
