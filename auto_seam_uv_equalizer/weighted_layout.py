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
MIN_WEIGHT_FRACTION = 1.0e-6


@dataclass
class IslandLayout:
    face_indices: tuple[int, ...]
    loop_indices: tuple[int, ...]
    surface_area: float
    face_count: int
    polygon_density: float
    normalized_density: float = 1.0
    weight: float = 0.0
    allocated_rect: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class LayoutReport:
    island_count: int
    total_surface_area: float
    minimum_weight: float
    maximum_weight: float
    globally_scaled: bool = False


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


def weighted_rectangles(weights, rect=(0.0, 0.0, 1.0, 1.0)):
    """Stable slice-and-dice weighted partition, alternating on the longest axis."""
    if not weights:
        return []
    safe = [value if math.isfinite(value) and value > EPSILON else EPSILON for value in weights]
    floor = max(sum(safe) * MIN_WEIGHT_FRACTION, EPSILON)
    safe = [max(value, floor) for value in safe]
    result = [None] * len(safe)

    def partition(indices, bounds):
        x0, y0, x1, y1 = bounds
        if len(indices) == 1:
            result[indices[0]] = bounds
            return
        total = sum(safe[index] for index in indices)
        target = total * 0.5
        running = 0.0
        split = 1
        for position, index in enumerate(indices[:-1], 1):
            running += safe[index]
            split = position
            if running >= target:
                break
        first, second = indices[:split], indices[split:]
        ratio = sum(safe[index] for index in first) / total
        if (x1 - x0) >= (y1 - y0):
            cut = x0 + (x1 - x0) * ratio
            partition(first, (x0, y0, cut, y1)); partition(second, (cut, y0, x1, y1))
        else:
            cut = y0 + (y1 - y0) * ratio
            partition(first, (x0, y0, x1, cut)); partition(second, (x0, cut, x1, y1))

    partition(list(range(len(safe))), rect)
    return result


def _world_polygon_area(obj, polygon):
    points = [obj.matrix_world @ obj.data.vertices[index].co for index in polygon.vertices]
    if len(points) < 3:
        return 0.0
    origin = points[0]
    return sum((points[index] - origin).cross(points[index + 1] - origin).length * 0.5
               for index in range(1, len(points) - 1))


def weighted_layout_object(obj, density_influence, scale_mode, texture_size,
                           padding_pixels, scope="SELECTED_FACES") -> LayoutReport:
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
    rectangles = weighted_rectangles(weights)
    for island, density, norm, weight, rectangle in zip(islands, densities, normalized, weights, rectangles):
        island.polygon_density = density; island.normalized_density = norm
        island.weight = weight; island.allocated_rect = rectangle

    padding = max(0.0, float(padding_pixels)) / max(1, int(texture_size))
    prepared = []
    global_scale = 1.0
    for island in islands:
        x0, y0, x1, y1 = island.allocated_rect
        inset = min(padding, (x1 - x0) * 0.45, (y1 - y0) * 0.45)
        usable = (x0 + inset, y0 + inset, x1 - inset, y1 - inset)
        coords = [uv_layer.uv[index].vector for index in island.loop_indices]
        bounds = (min(p.x for p in coords), min(p.y for p in coords),
                  max(p.x for p in coords), max(p.y for p in coords))
        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
        if width <= EPSILON or height <= EPSILON:
            raise RuntimeError("a UV island has zero width or height")
        fit = min((usable[2] - usable[0]) / width, (usable[3] - usable[1]) / height)
        if scale_mode == "PRESERVE_TEXEL_DENSITY":
            global_scale = min(global_scale, fit)
        prepared.append((island, usable, bounds, fit))

    globally_scaled = scale_mode == "PRESERVE_TEXEL_DENSITY" and global_scale < 1.0
    for island, usable, bounds, fit in prepared:
        scale = fit if scale_mode == "ALLOCATE_BY_IMPORTANCE" else min(1.0, global_scale)
        source_center = ((bounds[0] + bounds[2]) * 0.5, (bounds[1] + bounds[3]) * 0.5)
        target_center = ((usable[0] + usable[2]) * 0.5, (usable[1] + usable[3]) * 0.5)
        for index in island.loop_indices:
            uv = uv_layer.uv[index].vector
            uv.x = target_center[0] + (uv.x - source_center[0]) * scale
            uv.y = target_center[1] + (uv.y - source_center[1]) * scale
    mesh.update()
    return LayoutReport(len(islands), sum(i.surface_area for i in islands), min(weights), max(weights), globally_scaled)
