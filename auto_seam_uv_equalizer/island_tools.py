"""UV island helpers for material-based scaling."""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from typing import DefaultDict


def parse_material_scale_rules(rule_text: str) -> tuple[dict[str, float], list[str]]:
    """Parse comma-separated MaterialName=Scale rules."""
    rules: dict[str, float] = {}
    warnings: list[str] = []

    for raw_item in (rule_text or "").split(","):
        item = raw_item.strip()
        if not item:
            continue

        if "=" not in item:
            warnings.append(f"Ignored invalid material scale rule '{item}': expected MaterialName=Scale.")
            continue

        material_name, raw_scale = [part.strip() for part in item.split("=", 1)]
        if not material_name:
            warnings.append(f"Ignored invalid material scale rule '{item}': material name is empty.")
            continue

        try:
            scale = float(raw_scale)
        except ValueError:
            warnings.append(f"Ignored invalid material scale rule '{item}': scale is not a number.")
            continue

        if scale <= 0.0:
            warnings.append(f"Ignored invalid material scale rule '{item}': scale must be greater than 0.")
            continue

        rules[material_name] = scale

    return rules, warnings


def _build_edge_to_faces(mesh) -> dict[int, list[int]]:
    edge_to_faces: DefaultDict[int, list[int]] = defaultdict(list)
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            edge_index = mesh.loops[loop_index].edge_index
            edge_to_faces[edge_index].append(polygon.index)
    return dict(edge_to_faces)


def _find_face_islands(mesh) -> list[list[int]]:
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


def _material_name_for_index(obj, material_index: int) -> str | None:
    if material_index < 0 or material_index >= len(obj.material_slots):
        return None
    material = obj.material_slots[material_index].material
    if material is None:
        return None
    return material.name


def _representative_material_name(obj, face_indices: list[int]) -> str | None:
    mesh = obj.data
    weighted_materials: Counter[str] = Counter()

    for face_index in face_indices:
        polygon = mesh.polygons[face_index]
        material_name = _material_name_for_index(obj, polygon.material_index)
        if material_name:
            weighted_materials[material_name] += max(polygon.area, 1.0e-8)

    if not weighted_materials:
        return None

    return weighted_materials.most_common(1)[0][0]


def _scale_island_uvs(mesh, uv_layer, face_indices: list[int], scale: float) -> None:
    loop_indices = []
    for face_index in face_indices:
        loop_indices.extend(mesh.polygons[face_index].loop_indices)

    if not loop_indices:
        return

    center = sum((uv_layer.data[loop_index].uv.copy() for loop_index in loop_indices), uv_layer.data[loop_indices[0]].uv.copy() * 0.0)
    center /= len(loop_indices)

    for loop_index in loop_indices:
        uv = uv_layer.data[loop_index].uv
        uv_layer.data[loop_index].uv = center + (uv - center) * scale


def apply_material_uv_scale_rules(obj, rules: dict[str, float]) -> int:
    """Scale seam-delimited UV islands according to their representative material name."""
    if obj is None or obj.type != "MESH" or not rules:
        return 0

    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return 0

    scaled_islands = 0
    for face_indices in _find_face_islands(mesh):
        material_name = _representative_material_name(obj, face_indices)
        if material_name not in rules:
            continue

        _scale_island_uvs(mesh, uv_layer, face_indices, rules[material_name])
        scaled_islands += 1

    mesh.update()
    return scaled_islands
