"""Weighted, aspect-preserving UV island layout primitives and Blender backend."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from .island_tools import find_uv_islands
from .mesh_utils import build_mesh_topology
from .uv_protection import (assert_plan_does_not_modify_finished, island_state,
                            validate_protection_consistency)


EPSILON = 1.0e-12
DENSITY_MIN = 0.25
DENSITY_MAX = 4.0


@dataclass
class IslandLayout:
    face_indices: tuple[int, ...]
    loop_indices: tuple[int, ...]
    surface_area: float
    face_count: int
    polygon_density: float
    normalized_density: float = 1.0
    weight: float = 0.0
    uv_aspect: float = 1.0
    uv_area: float = 0.0
    packed_rect: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class LayoutReport:
    island_count: int
    total_surface_area: float
    minimum_weight: float
    maximum_weight: float
    globally_scaled: bool = False
    maximum_area_ratio_error: float = 0.0
    uv_utilization: float = 0.0


def calculate_weights(areas, face_counts, density_influence: float):
    """Return (densities, normalized densities, weights) using median normalization."""
    if len(areas) != len(face_counts):
        raise ValueError("areas and face_counts must have the same length")
    densities = [count / area if math.isfinite(area) and area > EPSILON else 0.0
                 for area, count in zip(areas, face_counts)]
    valid = [value for value in densities if math.isfinite(value) and value > 0.0]
    median_density = median(valid) if valid else 1.0
    if not math.isfinite(median_density) or median_density <= EPSILON:
        median_density = 1.0
    influence = min(1.0, max(0.0, density_influence))
    normalized = [value / median_density for value in densities]
    # Shift the whole normalized set together when it fits inside the clamp;
    # this retains meaningful inter-island ratios (for example 16 ** .25 == 2).
    positive = [value for value in normalized if value > 0.0 and math.isfinite(value)]
    factor = max(1.0, DENSITY_MIN / min(positive)) if positive else 1.0
    if positive and max(positive) * factor > DENSITY_MAX:
        factor = DENSITY_MAX / max(positive)
    normalized = [min(DENSITY_MAX, max(DENSITY_MIN, value * factor))
                  for value in normalized]
    weights = [area * (density ** influence) for area, density in zip(areas, normalized)]
    return densities, normalized, weights


def importance_boxes(weights, aspects):
    """Return unit-total-area boxes preserving each requested aspect ratio."""
    if not weights or len(weights) != len(aspects):
        raise ValueError("weights and aspects must have equal non-zero length")
    if any(not math.isfinite(value) or value <= EPSILON for value in weights):
        raise ValueError("weights must be finite and positive")
    if any(not math.isfinite(value) or value <= EPSILON for value in aspects):
        raise ValueError("aspects must be finite and positive")
    total = sum(weights)
    return [(math.sqrt((weight / total) * aspect),
             math.sqrt((weight / total) / aspect))
            for weight, aspect in zip(weights, aspects)]


def _subtract_occupied(free, occupied):
    """Subtract one clipped rectangle and prune duplicate/contained free areas."""
    ox, oy, ow, oh = occupied
    remaining = []
    for rx, ry, rw, rh in free:
        if ox >= rx + rw - EPSILON or ox + ow <= rx + EPSILON or \
                oy >= ry + rh - EPSILON or oy + oh <= ry + EPSILON:
            remaining.append((rx, ry, rw, rh)); continue
        if ox > rx + EPSILON: remaining.append((rx, ry, ox - rx, rh))
        if ox + ow < rx + rw - EPSILON: remaining.append((ox + ow, ry, rx + rw - ox - ow, rh))
        if oy > ry + EPSILON: remaining.append((rx, ry, rw, oy - ry))
        if oy + oh < ry + rh - EPSILON: remaining.append((rx, oy + oh, rw, ry + rh - oy - oh))
    return [candidate for i, candidate in enumerate(remaining)
            if candidate[2] > EPSILON and candidate[3] > EPSILON and not any(
                i != j and other[0] <= candidate[0] + EPSILON
                and other[1] <= candidate[1] + EPSILON
                and other[0] + other[2] >= candidate[0] + candidate[2] - EPSILON
                and other[1] + other[3] >= candidate[1] + candidate[3] - EPSILON
                for j, other in enumerate(remaining))]


def _maxrects_pack(boxes, rect, padding, obstacles=(), allow_rotation=False):
    """Pack non-rotated boxes using deterministic MaxRects best-area-fit."""
    x0, y0, x1, y1 = rect
    free = [(x0, y0, x1 - x0, y1 - y0)]
    # An obstacle receives one padding halo and each movable receives its
    # existing one-padding halo: the body-to-body distance remains 2*padding,
    # exactly matching movable-to-movable semantics (never double-added).
    for left, bottom, right, top in obstacles:
        clipped = (max(x0, left - padding), max(y0, bottom - padding),
                   min(x1, right + padding), min(y1, top + padding))
        if clipped[0] < clipped[2] and clipped[1] < clipped[3]:
            free = _subtract_occupied(
                free, (clipped[0], clipped[1], clipped[2] - clipped[0], clipped[3] - clipped[1]))
    placed = [None] * len(boxes)
    order = sorted(range(len(boxes)), key=lambda i: (
        -(boxes[i][0] + 2 * padding) * (boxes[i][1] + 2 * padding),
        -max(boxes[i]), i))
    for index in order:
        orientations = [(boxes[index][0], boxes[index][1], False)]
        if allow_rotation and abs(boxes[index][0] - boxes[index][1]) > EPSILON:
            orientations.append((boxes[index][1], boxes[index][0], True))
        candidates = []
        for body_width, body_height, rotated in orientations:
            width, height = body_width + 2 * padding, body_height + 2 * padding
            for free_index, (fx, fy, fw, fh) in enumerate(free):
                if width <= fw + EPSILON and height <= fh + EPSILON:
                    candidates.append((fw * fh - width * height,
                                       min(fw - width, fh - height), fy, fx,
                                       free_index, rotated, body_width, body_height))
        if not candidates:
            return None
        _, _, _, _, chosen, rotated, body_width, body_height = min(candidates)
        width, height = body_width + 2 * padding, body_height + 2 * padding
        fx, fy, fw, fh = free.pop(chosen)
        occupied = (fx, fy, width, height)
        placed[index] = (fx + padding, fy + padding,
                         fx + padding + body_width, fy + padding + body_height,
                         rotated)
        # MaxRects splitting: retain every portion of every free rectangle not
        # covered by the newly occupied rectangle, then prune contained pieces.
        free = _subtract_occupied(free + [(fx, fy, fw, fh)], occupied)
    return placed


def pack_importance_boxes(weights, aspects, rect=(0.0, 0.0, 1.0, 1.0), padding=0.0,
                          obstacles=(), allow_rotation=False):
    """Find the largest shared scale and pack importance boxes transactionally."""
    unit = importance_boxes(weights, aspects)
    padding = max(0.0, float(padding))
    target_area = (rect[2] - rect[0]) * (rect[3] - rect[1])
    high = math.sqrt(target_area)  # sum of unpadded unit box areas is one
    low, best = 0.0, None
    for _ in range(28):
        mid = (low + high) * 0.5
        result = _maxrects_pack([(w * mid, h * mid) for w, h in unit], rect, padding,
                                obstacles, allow_rotation)
        if result is None:
            high = mid
        else:
            low, best = mid, result
    if best is None or low <= EPSILON:
        raise RuntimeError("importance rectangles cannot fit in the target UV region with the requested padding")
    return (best if allow_rotation else [rect[:4] for rect in best]), low


def _polygon_uv_area(mesh, uv_layer, face_indices):
    area = 0.0
    for face_index in face_indices:
        coords = [uv_layer.uv[index].vector for index in mesh.polygons[face_index].loop_indices]
        area += abs(sum(coords[index].x * coords[(index + 1) % len(coords)].y
                        - coords[(index + 1) % len(coords)].x * coords[index].y
                        for index in range(len(coords)))) * 0.5
    return area


def target_rectangle(target_region):
    """Return the permitted root rectangle for a weighted layout region."""
    try:
        return {"FULL": (0.0, 0.0, 1.0, 1.0),
                "LEFT_HALF": (0.0, 0.0, 0.5, 1.0),
                "RIGHT_HALF": (0.5, 0.0, 1.0, 1.0)}[target_region]
    except KeyError as exc:
        raise ValueError(f"unknown target UV region: {target_region}") from exc


def world_polygon_areas(obj):
    """Return robust world-space areas using Blender's n-gon tessellation."""
    mesh = obj.data
    mesh.calc_loop_triangles()
    world_positions = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
    areas = [0.0] * len(mesh.polygons)
    for triangle in mesh.loop_triangles:
        p0, p1, p2 = (world_positions[index] for index in triangle.vertices)
        areas[triangle.polygon_index] += (p1 - p0).cross(p2 - p0).length * 0.5
    return areas


def collect_weighted_islands(obj, scope="SELECTED_FACES", selected_face_indices=None):
    """Collect complete UV islands without changing mesh or UV state."""
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Weighted Island Layout requires an active UV map.")
    _, _, loop_to_face, _ = build_mesh_topology(mesh)
    polygon_areas = world_polygon_areas(obj)
    selected = (set(selected_face_indices) if selected_face_indices is not None else
                {polygon.index for polygon in mesh.polygons if polygon.select})
    result = []
    for loops in find_uv_islands(obj):
        faces = tuple(sorted({loop_to_face[index] for index in loops}))
        if scope == "SELECTED_FACES" and not selected.intersection(faces):
            continue
        if not faces:
            continue
        area = sum(polygon_areas[index] for index in faces)
        if not math.isfinite(area) or area <= EPSILON:
            continue
        island = IslandLayout(faces, tuple(sorted(loops)), area, len(faces), len(faces) / area)
        # Runtime-only ownership keeps the public data class and pure helpers simple.
        island.object = obj
        island.mesh = mesh
        island.uv_layer = uv_layer
        coords = [uv_layer.uv[index].vector for index in island.loop_indices]
        if not coords or any(not math.isfinite(value) for point in coords for value in (point.x, point.y)):
            raise RuntimeError("a UV island has invalid coordinates")
        bounds = (min(p.x for p in coords), min(p.y for p in coords),
                  max(p.x for p in coords), max(p.y for p in coords))
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if width <= EPSILON or height <= EPSILON:
            raise RuntimeError("a UV island has zero width or height")
        island.uv_aspect = width / height
        island.uv_area = _polygon_uv_area(mesh, uv_layer, faces)
        if not math.isfinite(island.uv_area) or island.uv_area <= EPSILON:
            raise RuntimeError("a UV island has zero or invalid UV area")
        island.source_bounds = bounds
        result.append(island)
    return result


def resolve_weighted_padding(settings):
    """Return the configured weighted-layout margin in UV-space units."""
    if settings.weighted_padding_mode == "RELATIVE":
        return max(0.0, float(settings.weighted_padding_uv))
    resolution = max(1, int(settings.weighted_texture_resolution))
    return max(0.0, float(settings.weighted_padding_pixels)) / resolution


def plan_weighted_layout(islands, density_influence, scale_mode, padding_uv,
                         target_region="FULL", obstacles=(), allow_rotation=False):
    """Build and validate a complete pending weighted layout without UV writes."""
    if not islands:
        raise RuntimeError("no non-zero-area UV islands are in the processing scope")
    densities, normalized, weights = calculate_weights(
        [item.surface_area for item in islands], [item.face_count for item in islands],
        density_influence)
    root = target_rectangle(target_region)
    padding = max(0.0, float(padding_uv))
    bbox_areas = [(item.source_bounds[2] - item.source_bounds[0]) *
                  (item.source_bounds[3] - item.source_bounds[1]) for item in islands]
    packing_weights = ([weight * bbox_area / item.uv_area
                        for weight, bbox_area, item in zip(weights, bbox_areas, islands)]
                       if scale_mode == "ALLOCATE_BY_IMPORTANCE" else bbox_areas)
    rectangles, _ = pack_importance_boxes(
        packing_weights, [item.uv_aspect for item in islands], root, padding,
        obstacles, allow_rotation)
    for item, density, norm, weight, rectangle in zip(
            islands, densities, normalized, weights, rectangles):
        item.polygon_density, item.normalized_density = density, norm
        item.weight, item.packed_rect = weight, rectangle[:4]

    fits = []
    for item, packed in zip(islands, rectangles):
        bounds, rect = item.source_bounds, item.packed_rect
        rotated = packed[4] if len(packed) > 4 else False
        source_width = (bounds[3] - bounds[1]) if rotated else (bounds[2] - bounds[0])
        source_height = (bounds[2] - bounds[0]) if rotated else (bounds[3] - bounds[1])
        fits.append(min((rect[2] - rect[0]) / source_width,
                        (rect[3] - rect[1]) / source_height))
    global_scale = min([1.0, *fits]) if scale_mode == "PRESERVE_TEXEL_DENSITY" else None
    actual_areas = []
    pending = []
    for index, item in enumerate(islands):
        bounds, packed = item.source_bounds, rectangles[index]
        rect, rotated = packed[:4], (packed[4] if len(packed) > 4 else False)
        source_width = (bounds[3] - bounds[1]) if rotated else (bounds[2] - bounds[0])
        scale = ((rect[2] - rect[0]) / source_width
                 if global_scale is None else global_scale)
        source_center = ((bounds[0] + bounds[2]) * .5, (bounds[1] + bounds[3]) * .5)
        target_center = ((rect[0] + rect[2]) * .5, (rect[1] + rect[3]) * .5)
        coordinates = []
        for loop_index in item.loop_indices:
            uv = item.uv_layer.uv[loop_index].vector
            du, dv = uv.x - source_center[0], uv.y - source_center[1]
            u = target_center[0] + ((-dv if rotated else du) * scale)
            v = target_center[1] + ((du if rotated else dv) * scale)
            if not (math.isfinite(u) and math.isfinite(v) and
                    root[0] - 1e-9 <= u <= root[2] + 1e-9 and
                    root[1] - 1e-9 <= v <= root[3] + 1e-9):
                raise RuntimeError("weighted layout produced UVs outside the target region")
            coordinates.append((loop_index, u, v))
        pending.append((item, coordinates))
        actual_areas.append(item.uv_area * scale * scale)
    # MaxRects body rectangles must remain disjoint and maintain requested padding.
    for first in range(len(rectangles)):
        for second in range(first + 1, len(rectangles)):
            a, b = rectangles[first], rectangles[second]
            if (min(a[2], b[2]) - max(a[0], b[0]) > -2 * padding + EPSILON and
                    min(a[3], b[3]) - max(a[1], b[1]) > -2 * padding + EPSILON):
                raise RuntimeError("weighted layout produced overlapping island bounds")
    actual_total, weight_total = sum(actual_areas), sum(weights)
    maximum_error = (max(abs((area / actual_total) / (weight / weight_total) - 1.0)
                         for area, weight in zip(actual_areas, weights))
                     if scale_mode == "ALLOCATE_BY_IMPORTANCE" else 0.0)
    utilization = actual_total / ((root[2] - root[0]) * (root[3] - root[1]))
    report = LayoutReport(len(islands), sum(item.surface_area for item in islands),
                          min(weights), max(weights),
                          scale_mode == "PRESERVE_TEXEL_DENSITY" and global_scale < 1.0,
                          maximum_error, utilization)
    return pending, report


def apply_weighted_plan(pending):
    """Commit a previously validated plan; callers may snapshot for rollback."""
    meshes = set()
    for item, coordinates in pending:
        for loop_index, u, v in coordinates:
            item.uv_layer.uv[loop_index].vector = (u, v)
        meshes.add(item.mesh)
    for mesh in meshes:
        mesh.update()


def weighted_layout_object(obj, density_influence, scale_mode, padding_uv,
                           scope="SELECTED_FACES", target_region="FULL",
                           allow_rotation=False) -> LayoutReport:
    """Lay out one object's active-map islands (the backward-compatible wrapper)."""
    islands = collect_weighted_islands(obj, scope)
    validate_protection_consistency(obj)
    movable, fixed = [], []
    for island in islands:
        (fixed if island_state(obj.data, island.face_indices).effectively_layout_locked
         else movable).append(island)
    if not movable:
        raise RuntimeError("all target UV islands are protected")
    obstacles = [item.source_bounds for item in fixed]
    pending, report = plan_weighted_layout(
        movable, density_influence, scale_mode, padding_uv, target_region,
        obstacles, allow_rotation)
    assert_plan_does_not_modify_finished(obj.data,
                                         (loop for item, _ in pending for loop in item.loop_indices))
    apply_weighted_plan(pending)
    return report


def incremental_pack_object(obj, density_influence, scale_mode, padding_uv,
                            target_region="FULL", allow_rotation=False,
                            selected_face_indices=None):
    """Transactionally pack only selected, editable islands around all others."""
    all_islands = collect_weighted_islands(obj, "WHOLE_OBJECT")
    validate_protection_consistency(obj)
    selected = ({face.index for face in obj.data.polygons if face.select}
                if selected_face_indices is None else set(selected_face_indices))
    movable, obstacles = [], []
    for island in all_islands:
        state = island_state(obj.data, island.face_indices)
        if selected.intersection(island.face_indices) and not state.effectively_layout_locked:
            movable.append(island)
        else:
            obstacles.append(island.source_bounds)
    if not movable:
        raise RuntimeError("no selected editable UV islands")
    pending, report = plan_weighted_layout(
        movable, density_influence, scale_mode, padding_uv, target_region,
        obstacles, allow_rotation)
    assert_plan_does_not_modify_finished(
        obj.data, (loop for item, _ in pending for loop in item.loop_indices))
    # Planning is complete before the first write. apply_weighted_plan cannot
    # partially fail under normal Blender RNA assignment, but retain a rollback
    # snapshot as the transaction's final guarantee.
    layer = obj.data.uv_layers.active
    before = {loop: tuple(layer.uv[loop].vector)
              for item in movable for loop in item.loop_indices}
    try:
        apply_weighted_plan(pending)
    except Exception:
        for loop, uv in before.items():
            layer.uv[loop].vector = uv
        obj.data.update()
        raise
    return report


def shared_weighted_layout(objects, density_influence, scale_mode, padding_uv,
                           scope="SELECTED_FACES", target_region="FULL",
                           selected_faces_by_mesh=None, allow_rotation=False):
    """Collect every object's islands into one deterministic global atlas transaction."""
    selected_faces_by_mesh = selected_faces_by_mesh or {}
    ordered = sorted(objects, key=lambda obj: obj.name_full)
    islands = []
    for obj in ordered:
        key = obj.data.as_pointer() if hasattr(obj.data, "as_pointer") else id(obj.data)
        islands.extend(collect_weighted_islands(
            obj, scope, selected_faces_by_mesh.get(key)))
    islands.sort(key=lambda item: (item.object.name_full, min(item.face_indices)))
    for obj in ordered:
        validate_protection_consistency(obj)
    movable, fixed = [], []
    for island in islands:
        (fixed if island_state(island.mesh, island.face_indices).effectively_layout_locked
         else movable).append(island)
    if not movable:
        raise RuntimeError("all target UV islands are protected")
    meshes = {item.mesh for item in islands}
    snapshots = {mesh: [tuple(entry.vector) for entry in mesh.uv_layers.active.uv]
                 for mesh in meshes}
    try:
        pending, report = plan_weighted_layout(
            movable, density_influence, scale_mode, padding_uv, target_region,
            [item.source_bounds for item in fixed], allow_rotation)
        for mesh in meshes:
            assert_plan_does_not_modify_finished(
                mesh, (loop for item, _ in pending if item.mesh == mesh for loop in item.loop_indices))
        apply_weighted_plan(pending)
    except Exception:
        for mesh, values in snapshots.items():
            uv_layer = mesh.uv_layers.active
            for index, vector in enumerate(values):
                uv_layer.uv[index].vector = vector
            mesh.update()
        raise
    return report
