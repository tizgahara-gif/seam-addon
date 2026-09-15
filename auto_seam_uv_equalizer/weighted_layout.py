"""Weighted, aspect-preserving UV island layout primitives and Blender backend."""

from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import median

from .island_tools import find_uv_islands
from .mesh_utils import build_mesh_topology


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


def _maxrects_pack(boxes, rect, padding):
    """Pack non-rotated boxes using deterministic MaxRects best-area-fit."""
    x0, y0, x1, y1 = rect
    free = [(x0, y0, x1 - x0, y1 - y0)]
    placed = [None] * len(boxes)
    order = sorted(range(len(boxes)), key=lambda i: (
        -(boxes[i][0] + 2 * padding) * (boxes[i][1] + 2 * padding),
        -max(boxes[i]), i))
    for index in order:
        width, height = boxes[index][0] + 2 * padding, boxes[index][1] + 2 * padding
        candidates = []
        for free_index, (fx, fy, fw, fh) in enumerate(free):
            if width <= fw + EPSILON and height <= fh + EPSILON:
                candidates.append((fw * fh - width * height,
                                   min(fw - width, fh - height), fy, fx, free_index))
        if not candidates:
            return None
        _, _, _, _, chosen = min(candidates)
        fx, fy, fw, fh = free.pop(chosen)
        occupied = (fx, fy, width, height)
        placed[index] = (fx + padding, fy + padding,
                         fx + padding + boxes[index][0], fy + padding + boxes[index][1])
        # MaxRects splitting: retain every portion of every free rectangle not
        # covered by the newly occupied rectangle, then prune contained pieces.
        remaining = []
        ox, oy, ow, oh = occupied
        for rx, ry, rw, rh in free + [(fx, fy, fw, fh)]:
            if ox >= rx + rw - EPSILON or ox + ow <= rx + EPSILON or \
                    oy >= ry + rh - EPSILON or oy + oh <= ry + EPSILON:
                remaining.append((rx, ry, rw, rh)); continue
            if ox > rx + EPSILON: remaining.append((rx, ry, ox - rx, rh))
            if ox + ow < rx + rw - EPSILON: remaining.append((ox + ow, ry, rx + rw - ox - ow, rh))
            if oy > ry + EPSILON: remaining.append((rx, ry, rw, oy - ry))
            if oy + oh < ry + rh - EPSILON: remaining.append((rx, oy + oh, rw, ry + rh - oy - oh))
        free = [candidate for i, candidate in enumerate(remaining)
                if candidate[2] > EPSILON and candidate[3] > EPSILON and not any(
                    i != j and other[0] <= candidate[0] + EPSILON
                    and other[1] <= candidate[1] + EPSILON
                    and other[0] + other[2] >= candidate[0] + candidate[2] - EPSILON
                    and other[1] + other[3] >= candidate[1] + candidate[3] - EPSILON
                    for j, other in enumerate(remaining))]
    return placed


def pack_importance_boxes(weights, aspects, rect=(0.0, 0.0, 1.0, 1.0), padding=0.0):
    """Find the largest shared scale and pack importance boxes transactionally."""
    unit = importance_boxes(weights, aspects)
    padding = max(0.0, float(padding))
    target_area = (rect[2] - rect[0]) * (rect[3] - rect[1])
    high = math.sqrt(target_area)  # sum of unpadded unit box areas is one
    low, best = 0.0, None
    for _ in range(28):
        mid = (low + high) * 0.5
        result = _maxrects_pack([(w * mid, h * mid) for w, h in unit], rect, padding)
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


def _world_polygon_area(obj, polygon):
    points = [obj.matrix_world @ obj.data.vertices[index].co for index in polygon.vertices]
    if len(points) < 3:
        return 0.0
    origin = points[0]
    return sum((points[index] - origin).cross(points[index + 1] - origin).length * 0.5
               for index in range(1, len(points) - 1))


def weighted_layout_object(obj, density_influence, scale_mode, texture_size,
                           padding_pixels, scope="SELECTED_FACES", target_region="FULL") -> LayoutReport:
    """Lay out active-map islands using world surface area and polygon density."""
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise RuntimeError("Weighted Island Layout requires an active UV map.")
    _, _, loop_to_face, _ = build_mesh_topology(mesh)
    selected = {polygon.index for polygon in mesh.polygons if polygon.select}
    raw_islands = find_uv_islands(obj)
    islands = []
    for loops in raw_islands:
        faces = tuple(sorted({loop_to_face[index] for index in loops}))
        if scope == "SELECTED_FACES":
            faces = tuple(index for index in faces if index in selected)
            loops = {loop for face in faces for loop in mesh.polygons[face].loop_indices}
        if not faces:
            continue
        area = sum(_world_polygon_area(obj, mesh.polygons[index]) for index in faces)
        if not math.isfinite(area) or area <= EPSILON:
            continue
        islands.append(IslandLayout(faces, tuple(sorted(loops)), area, len(faces), len(faces) / area))
    if not islands:
        raise RuntimeError("no non-zero-area UV islands are in the processing scope")

    densities, normalized, weights = calculate_weights(
        [island.surface_area for island in islands], [island.face_count for island in islands], density_influence)
    bounds_by_island = []
    for island in islands:
        coords = [uv_layer.uv[index].vector for index in island.loop_indices]
        bounds = (min(p.x for p in coords), min(p.y for p in coords),
                  max(p.x for p in coords), max(p.y for p in coords))
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if width <= EPSILON or height <= EPSILON:
            raise RuntimeError("a UV island has zero width or height")
        island.uv_aspect = width / height
        island.uv_area = _polygon_uv_area(mesh, uv_layer, island.face_indices)
        if not math.isfinite(island.uv_area) or island.uv_area <= EPSILON:
            raise RuntimeError("a UV island has zero or invalid UV area")
        bounds_by_island.append(bounds)
    root = target_rectangle(target_region)
    padding = max(0.0, float(padding_pixels)) / max(1, int(texture_size))
    # A non-rectangular island may fill only part of its BBox.  Compensating by
    # BBox/polygon fill here makes the *polygon* UV areas (not merely BBoxes)
    # proportional to importance after a common scale is applied.
    bbox_areas = [(bounds[2] - bounds[0]) * (bounds[3] - bounds[1])
                  for bounds in bounds_by_island]
    packing_weights = ([weight * bbox_area / island.uv_area
                        for weight, bbox_area, island in zip(weights, bbox_areas, islands)]
                       if scale_mode == "ALLOCATE_BY_IMPORTANCE" else bbox_areas)
    rectangles, _packed_global_scale = pack_importance_boxes(
        packing_weights, [island.uv_aspect for island in islands], root, padding)
    for island, density, norm, weight, rectangle in zip(islands, densities, normalized, weights, rectangles):
        island.polygon_density = density; island.normalized_density = norm
        island.weight = weight; island.packed_rect = rectangle

    prepared = []
    global_scale = 1.0
    for island, bounds in zip(islands, bounds_by_island):
        x0, y0, x1, y1 = island.packed_rect
        usable = (x0, y0, x1, y1)
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        fit = min((usable[2] - usable[0]) / width, (usable[3] - usable[1]) / height)
        if scale_mode == "PRESERVE_TEXEL_DENSITY":
            global_scale = min(global_scale, fit)
        prepared.append((island, usable, bounds, fit))

    globally_scaled = scale_mode == "PRESERVE_TEXEL_DENSITY" and global_scale < 1.0
    packed_scales_by_island = None
    if scale_mode == "ALLOCATE_BY_IMPORTANCE":
        # The largest common constant that lets every final polygon area equal
        # ``constant * weight`` while exactly matching its packed BBox.
        # Every packed body box is its source BBox times one uniform island
        # scale; all ideal boxes received the same global packing scale.
        packed_scales_by_island = [
            (item[1][2] - item[1][0]) / (item[2][2] - item[2][0]) for item in prepared]
    actual_areas = []
    for prepared_index, (island, usable, bounds, fit) in enumerate(prepared):
        scale = (packed_scales_by_island[prepared_index]
                 if packed_scales_by_island is not None else min(1.0, global_scale))
        source_center = ((bounds[0] + bounds[2]) * 0.5, (bounds[1] + bounds[3]) * 0.5)
        target_center = ((usable[0] + usable[2]) * 0.5, (usable[1] + usable[3]) * 0.5)
        pending = []
        for index in island.loop_indices:
            uv = uv_layer.uv[index].vector
            pending.append((index, target_center[0] + (uv.x - source_center[0]) * scale,
                            target_center[1] + (uv.y - source_center[1]) * scale))
        prepared[prepared_index] = (*prepared[prepared_index], pending)
        actual_areas.append(island.uv_area * scale * scale)
    epsilon = 1.0e-9
    for item in prepared:
        for _, u, v in item[4]:
            if not (root[0] - epsilon <= u <= root[2] + epsilon
                    and root[1] - epsilon <= v <= root[3] + epsilon):
                raise RuntimeError("weighted layout produced UVs outside the target region")
    for item in prepared:
        for index, u, v in item[4]:
            uv_layer.uv[index].vector = (u, v)
    mesh.update()
    maximum_error = 0.0
    if packed_scales_by_island is not None:
        actual_total, weight_total = sum(actual_areas), sum(weights)
        maximum_error = max(abs((area / actual_total) / (weight / weight_total) - 1.0)
                            for area, weight in zip(actual_areas, weights))
    utilization = sum(actual_areas) / ((root[2] - root[0]) * (root[3] - root[1]))
    return LayoutReport(len(islands), sum(i.surface_area for i in islands), min(weights), max(weights),
                        globally_scaled, maximum_error, utilization)
