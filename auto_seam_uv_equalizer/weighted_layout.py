"""Weighted, aspect-preserving UV island layout primitives and Blender backend."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from .island_tools import find_uv_islands
from .mesh_utils import build_mesh_topology
from .uv_protection import (assert_plan_does_not_modify_finished, island_state,
                            validate_protection_consistency)


EPSILON = 1.0e-9
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
    packed_rect: PackedIsland | None = None


@dataclass(frozen=True)
class PackedIsland:
    """A MaxRects placement, including the orientation selected by the planner."""
    x0: float
    y0: float
    x1: float
    y1: float
    rotation_step: int = 0

    def __iter__(self):
        return iter((self.x0, self.y0, self.x1, self.y1))

    def __getitem__(self, index):
        values = (*tuple(self), self.rotation_step)
        return values[index]

    def __len__(self):
        return 5


@dataclass(frozen=True)
class LayoutReport:
    island_count: int
    total_surface_area: float
    minimum_weight: float
    maximum_weight: float
    globally_scaled: bool = False
    maximum_area_ratio_error: float = 0.0
    uv_utilization: float = 0.0
    rotated_island_count: int = 0


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


def rotation_steps_for_mode(mode):
    """Resolve the UI mode to deterministic 15-degree integer steps."""
    try:
        return {"NONE": (0,), "STEP_90": (0, 6),
                "STEP_15": tuple(range(12))}[mode]
    except KeyError as exc:
        raise ValueError(f"unknown weighted rotation mode: {mode}") from exc


@dataclass(frozen=True)
class RotationCandidate:
    rotation_step: int
    width: float
    height: float


def rotation_candidates(points, target_width, target_height, rotation_steps):
    """Cache actual-point bounding boxes after each requested rotation."""
    if not points:
        points = ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5))
    min_u, max_u = min(p[0] for p in points), max(p[0] for p in points)
    min_v, max_v = min(p[1] for p in points), max(p[1] for p in points)
    source_width, source_height = max_u - min_u, max_v - min_v
    if source_width <= EPSILON or source_height <= EPSILON:
        raise ValueError("rotation candidate source has zero width or height")
    # importance_boxes guarantees these two ratios agree: keep one uniform scale.
    scale = target_width / source_width
    pivot = ((min_u + max_u) * .5, (min_v + max_v) * .5)
    result = []
    for step in rotation_steps:
        if not isinstance(step, int) or not 0 <= step < 12:
            raise ValueError("rotation steps must be integers from 0 through 11")
        angle = math.radians(step * 15.0)
        cosine, sine = math.cos(angle), math.sin(angle)
        rotated = [((p[0] - pivot[0]) * cosine - (p[1] - pivot[1]) * sine,
                    (p[0] - pivot[0]) * sine + (p[1] - pivot[1]) * cosine)
                   for p in points]
        width = (max(p[0] for p in rotated) - min(p[0] for p in rotated)) * scale
        height = (max(p[1] for p in rotated) - min(p[1] for p in rotated)) * scale
        result.append(RotationCandidate(step, width, height))
    return tuple(result)


def _trial_orders(candidates, importance, multi_trial):
    indices = tuple(range(len(candidates)))
    def dims(i):
        return candidates[i][0].width, candidates[i][0].height
    keys = [lambda i: (-(dims(i)[0] * dims(i)[1]), -max(dims(i)), i)]
    if multi_trial:
        keys.extend((
            lambda i: (-max(dims(i)), -(dims(i)[0] * dims(i)[1]), i),
            lambda i: (-max(dims(i)[0] / dims(i)[1], dims(i)[1] / dims(i)[0]), i),
            lambda i: (-importance[i], i),
            lambda i: (i,),
        ))
    return tuple(tuple(sorted(indices, key=key)) for key in keys)


def _maxrects_trial(candidates_by_island, rect, padding, obstacles, order):
    x0, y0, x1, y1 = rect
    free = [(x0, y0, x1 - x0, y1 - y0)]
    for left, bottom, right, top in obstacles:
        clipped = (max(x0, left - padding), max(y0, bottom - padding),
                   min(x1, right + padding), min(y1, top + padding))
        if clipped[0] < clipped[2] and clipped[1] < clipped[3]:
            free = _subtract_occupied(free, (clipped[0], clipped[1],
                clipped[2] - clipped[0], clipped[3] - clipped[1]))
    placed = [None] * len(candidates_by_island)
    for index in order:
        choices = []
        for candidate in candidates_by_island[index]:
            width, height = candidate.width + 2 * padding, candidate.height + 2 * padding
            for free_index, (fx, fy, fw, fh) in enumerate(free):
                if width <= fw + 1e-9 and height <= fh + 1e-9:
                    choices.append((fw * fh - width * height,
                                    min(fw - width, fh - height), fy, fx,
                                    candidate.rotation_step, free_index, candidate))
        if not choices:
            return None
        *_, chosen, candidate = min(choices)
        width, height = candidate.width + 2 * padding, candidate.height + 2 * padding
        fx, fy, fw, fh = free.pop(chosen)
        placed[index] = PackedIsland(fx + padding, fy + padding,
            fx + padding + candidate.width, fy + padding + candidate.height,
            candidate.rotation_step)
        free = _subtract_occupied(free + [(fx, fy, fw, fh)], (fx, fy, width, height))
    occupied_width = max(p.x1 for p in placed) - min(p.x0 for p in placed)
    occupied_height = max(p.y1 for p in placed) - min(p.y0 for p in placed)
    score = (occupied_width * occupied_height, sum(r[2] * r[3] for r in free),
             sum(p.rotation_step for p in placed),
             tuple((p.x0, p.y0, p.rotation_step) for p in placed))
    return placed, score


def _maxrects_pack(boxes, rect, padding, obstacles=(), rotation_steps=(0,),
                   source_uvs=None, importance=None):
    """Pack cached orientation candidates using at most five deterministic trials."""
    source_uvs = source_uvs or [None] * len(boxes)
    importance = importance or [w * h for w, h in boxes]
    candidates = [rotation_candidates(points or
        ((0, 0), (box[0], 0), (box[0], box[1]), (0, box[1])),
        box[0], box[1], rotation_steps) for box, points in zip(boxes, source_uvs)]
    results = [_maxrects_trial(candidates, rect, padding, obstacles, order)
               for order in _trial_orders(candidates, importance, len(rotation_steps) == 12)]
    valid = [result for result in results if result is not None]
    return min(valid, key=lambda result: result[1])[0] if valid else None


def pack_importance_boxes(weights, aspects, rect=(0.0, 0.0, 1.0, 1.0), padding=0.0,
                          obstacles=(), rotation_steps=(0,), source_uvs=None):
    """Find the largest shared scale and pack importance boxes transactionally."""
    unit = importance_boxes(weights, aspects)
    padding = max(0.0, float(padding))
    high = math.sqrt((rect[2] - rect[0]) * (rect[3] - rect[1]))
    low, best = 0.0, None
    for _ in range(28):
        mid = (low + high) * .5
        result = _maxrects_pack([(w * mid, h * mid) for w, h in unit], rect, padding,
                                obstacles, rotation_steps, source_uvs, weights)
        if result is None:
            high = mid
        else:
            low, best = mid, result
    if best is None or low <= EPSILON:
        raise RuntimeError("importance rectangles cannot fit in the target UV region with the requested padding")
    return best, low

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
        island.in_scope = scope != "SELECTED_FACES" or bool(selected.intersection(faces))
        result.append(island)
    return result


def resolve_weighted_padding(settings):
    """Return the configured weighted-layout margin in UV-space units."""
    if settings.weighted_padding_mode == "RELATIVE":
        return max(0.0, float(settings.weighted_padding_uv))
    resolution = max(1, int(settings.weighted_texture_resolution))
    return max(0.0, float(settings.weighted_padding_pixels)) / resolution


def plan_weighted_layout(islands, density_influence, scale_mode, padding_uv,
                         target_region="FULL", obstacles=(), rotation_steps=(0,)):
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
    source_uvs = [tuple((item.uv_layer.uv[index].vector.x,
                          item.uv_layer.uv[index].vector.y)
                         for index in item.loop_indices) for item in islands]
    rectangles, _ = pack_importance_boxes(
        packing_weights, [item.uv_aspect for item in islands], root, padding,
        obstacles, rotation_steps, source_uvs)
    for item, density, norm, weight, rectangle in zip(
            islands, densities, normalized, weights, rectangles):
        item.polygon_density, item.normalized_density = density, norm
        item.weight, item.packed_rect = weight, rectangle

    fits = []
    for item, packed in zip(islands, rectangles):
        bounds, rect = item.source_bounds, item.packed_rect
        candidate = rotation_candidates(source_uvs[len(fits)],
            bounds[2] - bounds[0], bounds[3] - bounds[1], (packed.rotation_step,))[0]
        fits.append(min((rect.x1 - rect.x0) / candidate.width,
                        (rect.y1 - rect.y0) / candidate.height))
    global_scale = min([1.0, *fits]) if scale_mode == "PRESERVE_TEXEL_DENSITY" else None
    actual_areas = []
    pending = []
    for index, item in enumerate(islands):
        bounds, packed = item.source_bounds, rectangles[index]
        rect = packed
        candidate = rotation_candidates(source_uvs[index],
            bounds[2] - bounds[0], bounds[3] - bounds[1], (rect.rotation_step,))[0]
        scale = ((rect.x1 - rect.x0) / candidate.width
                 if global_scale is None else global_scale)
        angle = math.radians(rect.rotation_step * 15.0)
        cosine, sine = math.cos(angle), math.sin(angle)
        source_center = ((bounds[0] + bounds[2]) * .5, (bounds[1] + bounds[3]) * .5)
        target_center = ((rect.x0 + rect.x1) * .5, (rect.y0 + rect.y1) * .5)
        coordinates = []
        for loop_index in item.loop_indices:
            uv = item.uv_layer.uv[loop_index].vector
            du, dv = uv.x - source_center[0], uv.y - source_center[1]
            u = target_center[0] + (du * cosine - dv * sine) * scale
            v = target_center[1] + (du * sine + dv * cosine) * scale
            if not (math.isfinite(u) and math.isfinite(v) and
                    root[0] - 1e-9 <= u <= root[2] + 1e-9 and
                    root[1] - 1e-9 <= v <= root[3] + 1e-9):
                raise RuntimeError("weighted layout produced UVs outside the target region")
            coordinates.append((loop_index, u, v))
        pending.append((item, coordinates))
        actual_areas.append(item.uv_area * scale * scale)
        actual_bounds = (min(value[1] for value in coordinates),
                         min(value[2] for value in coordinates),
                         max(value[1] for value in coordinates),
                         max(value[2] for value in coordinates))
        planned_width = candidate.width * scale
        planned_height = candidate.height * scale
        planned_bounds = (target_center[0] - planned_width * .5,
                          target_center[1] - planned_height * .5,
                          target_center[0] + planned_width * .5,
                          target_center[1] + planned_height * .5)
        if any(abs(actual - planned) > 1e-9
               for actual, planned in zip(actual_bounds, planned_bounds)):
            raise RuntimeError("weighted layout transform does not match its planned bounds")
    # MaxRects body rectangles must remain disjoint and maintain requested padding.
    for first in range(len(rectangles)):
        for second in range(first + 1, len(rectangles)):
            a, b = rectangles[first], rectangles[second]
            if (min(a.x1, b.x1) - max(a.x0, b.x0) > -2 * padding + EPSILON and
                    min(a.y1, b.y1) - max(a.y0, b.y0) > -2 * padding + EPSILON):
                raise RuntimeError("weighted layout produced overlapping island bounds")
    actual_total, weight_total = sum(actual_areas), sum(weights)
    maximum_error = (max(abs((area / actual_total) / (weight / weight_total) - 1.0)
                         for area, weight in zip(actual_areas, weights))
                     if scale_mode == "ALLOCATE_BY_IMPORTANCE" else 0.0)
    utilization = actual_total / ((root[2] - root[0]) * (root[3] - root[1]))
    report = LayoutReport(len(islands), sum(item.surface_area for item in islands),
                          min(weights), max(weights),
                          scale_mode == "PRESERVE_TEXEL_DENSITY" and global_scale < 1.0,
                          maximum_error, utilization,
                          sum(rect.rotation_step != 0 for rect in rectangles))
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
                           rotation_steps=(0,), selected_face_indices=None) -> LayoutReport:
    """Lay out one object's active-map islands (the backward-compatible wrapper)."""
    islands = collect_weighted_islands(obj, scope, selected_face_indices)
    validate_protection_consistency(obj)
    movable, fixed = [], []
    for island in islands:
        state = island_state(obj.data, island.face_indices)
        (movable if island.in_scope and not state.effectively_layout_locked
         else fixed).append(island)
    if not movable:
        raise RuntimeError("all target UV islands are protected")
    obstacles = [item.source_bounds for item in fixed]
    pending, report = plan_weighted_layout(
        movable, density_influence, scale_mode, padding_uv, target_region,
        obstacles, rotation_steps)
    assert_plan_does_not_modify_finished(obj.data,
                                         (loop for item, _ in pending for loop in item.loop_indices))
    apply_weighted_plan(pending)
    return report


def incremental_pack_object(obj, density_influence, scale_mode, padding_uv,
                            target_region="FULL", rotation_steps=(0,),
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
        obstacles, rotation_steps)
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
                           selected_faces_by_mesh=None, rotation_steps=(0,)):
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
        state = island_state(island.mesh, island.face_indices)
        (movable if island.in_scope and not state.effectively_layout_locked
         else fixed).append(island)
    if not movable:
        raise RuntimeError("all target UV islands are protected")
    meshes = {item.mesh for item in islands}
    snapshots = {mesh: [tuple(entry.vector) for entry in mesh.uv_layers.active.uv]
                 for mesh in meshes}
    try:
        pending, report = plan_weighted_layout(
            movable, density_influence, scale_mode, padding_uv, target_region,
            [item.source_bounds for item in fixed], rotation_steps)
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
