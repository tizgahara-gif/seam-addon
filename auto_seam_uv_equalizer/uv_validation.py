"""UV validation and overlap geometry.

Blender RNA is copied into an immutable snapshot before any analysis.  This is
important in Edit Mode, where synchronising the edit BMesh can invalidate mesh
and UV collection references.
"""
from __future__ import annotations

from collections import defaultdict
from math import floor, sqrt
from typing import NamedTuple


class UVValidationError(RuntimeError):
    """A mesh cannot safely be inspected for UV validation."""


class UVTriangleSnapshot(NamedTuple):
    """Blender-independent data copied from one tessellated mesh triangle."""

    face_index: int
    loop_indices: tuple[int, int, int]
    vertex_indices: tuple[int, int, int]
    uv_points: tuple[tuple[float, float], tuple[float, float], tuple[float, float]]
    world_points: tuple[tuple[float, float, float], tuple[float, float, float],
                        tuple[float, float, float]]


class TriangleRecord(NamedTuple):
    obj: object
    face_index: int
    coordinates: tuple
    bbox: tuple[float, float, float, float]


def polygon_area_2d(points) -> float:
    return sum(
        point[0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * point[1]
        for index, point in enumerate(points)
    ) * 0.5


def signed_area(a, b, c):
    return ((b[0] - a[0]) * (c[1] - a[1])
            - (b[1] - a[1]) * (c[0] - a[0])) * 0.5


def prepare_validation_mesh(obj):
    """Synchronise Edit Mode and return freshly acquired Mesh/UV references."""
    if obj.mode == "EDIT" and not obj.update_from_editmode():
        raise UVValidationError("Could not synchronize Edit Mode mesh data.")

    # Do not move these acquisitions above update_from_editmode: those RNA
    # references may be stale after Blender flushes its edit BMesh.
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        raise UVValidationError("Active UV map required.")
    mesh.calc_loop_triangles()

    loop_count = len(mesh.loops)
    uv_count = len(uv_layer.uv)
    if uv_count != loop_count:
        raise UVValidationError("UV loop data is not synchronized with the mesh.")
    return mesh, uv_layer


def build_uv_triangle_snapshot(obj) -> tuple[UVTriangleSnapshot, ...]:
    """Copy Blender's loop-triangle data into immutable Python values."""
    mesh, uv_layer = prepare_validation_mesh(obj)
    uv_count = len(uv_layer.uv)
    vertex_count = len(mesh.vertices)
    matrix_world = obj.matrix_world.copy()
    triangles = []
    for triangle in mesh.loop_triangles:
        loop_indices = tuple(int(index) for index in triangle.loops)
        if len(loop_indices) != 3 or any(
                index < 0 or index >= uv_count for index in loop_indices):
            raise UVValidationError("Loop triangle contains an invalid UV loop index.")
        vertex_indices = tuple(int(index) for index in triangle.vertices)
        if len(vertex_indices) != 3 or any(
                index < 0 or index >= vertex_count for index in vertex_indices):
            raise UVValidationError("Loop triangle contains an invalid vertex index.")
        uv_points = tuple(
            (float(uv_layer.uv[index].vector[0]),
             float(uv_layer.uv[index].vector[1]))
            for index in loop_indices
        )
        world_points = tuple(
            tuple(float(value) for value in (matrix_world @ mesh.vertices[index].co))
            for index in vertex_indices
        )
        triangles.append(UVTriangleSnapshot(
            int(triangle.polygon_index), loop_indices, vertex_indices,
            uv_points, world_points,
        ))
    return tuple(triangles)


def triangles_from_object(obj, area_epsilon: float) -> list[TriangleRecord]:
    """Return non-degenerate UV triangles from the shared safe snapshot."""
    records = []
    for triangle in build_uv_triangle_snapshot(obj):
        if abs(polygon_area_2d(triangle.uv_points)) <= area_epsilon:
            continue
        xs, ys = zip(*triangle.uv_points)
        records.append(TriangleRecord(
            obj, triangle.face_index, triangle.uv_points,
            (min(xs), min(ys), max(xs), max(ys)),
        ))
    return records


def _subtract(a, b):
    return tuple(a[index] - b[index] for index in range(3))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _triangle_stretch(world_points, uv_points, coord_epsilon, area_epsilon):
    """Return the scale-invariant singular-value ratio, or ``None`` if degenerate."""
    e1 = _subtract(world_points[1], world_points[0])
    e2 = _subtract(world_points[2], world_points[0])
    x1_squared = _dot(e1, e1)
    if x1_squared <= coord_epsilon * coord_epsilon:
        return None
    x1 = sqrt(x1_squared)
    x2 = _dot(e2, e1) / x1
    y2_squared = max(0.0, _dot(e2, e2) - x2 * x2)
    if y2_squared <= coord_epsilon * coord_epsilon:
        return None
    y2 = sqrt(y2_squared)
    if abs(signed_area(*uv_points)) <= area_epsilon:
        return None

    du1 = uv_points[1][0] - uv_points[0][0]
    dv1 = uv_points[1][1] - uv_points[0][1]
    du2 = uv_points[2][0] - uv_points[0][0]
    dv2 = uv_points[2][1] - uv_points[0][1]
    j00, j10 = du1 / x1, dv1 / x1
    j01, j11 = (du2 - j00 * x2) / y2, (dv2 - j10 * x2) / y2

    a = j00 * j00 + j10 * j10
    b = j00 * j01 + j10 * j11
    c = j01 * j01 + j11 * j11
    trace = a + c
    disc = sqrt(max(0.0, (a - c) * (a - c) + 4.0 * b * b))
    lambda_max = (trace + disc) * 0.5
    lambda_min = (trace - disc) * 0.5
    sigma_max = sqrt(max(lambda_max, 0.0))
    sigma_min = sqrt(max(lambda_min, 0.0))
    if sigma_min <= coord_epsilon:
        return None
    return sigma_max / sigma_min


def validate_snapshot(snapshot, tolerance=1.0e-10, stretch_threshold=2.0):
    """Analyse immutable triangles without reading Blender RNA collections."""
    coord_epsilon = tolerance
    area_epsilon = tolerance
    flipped, zero, stretches = set(), set(), []
    summed_uv_area = 0.0
    for triangle in snapshot:
        points = triangle.uv_points
        area = signed_area(*points)
        if area < -area_epsilon:
            flipped.add(triangle.face_index)
        zero_edge = any(
            sum((points[index][axis] - points[(index + 1) % 3][axis]) ** 2
                for axis in range(2)) <= coord_epsilon * coord_epsilon
            for index in range(3)
        )
        stretch = _triangle_stretch(
            triangle.world_points, points, coord_epsilon, area_epsilon,
        )
        if abs(area) <= area_epsilon or zero_edge or stretch is None:
            zero.add(triangle.face_index)
        elif stretch == stretch:  # Do not allow NaN into reports.
            stretches.append(stretch)
        summed_uv_area += abs(area)

    average = sum(stretches) / len(stretches) if stretches else 0.0
    return {
        "flipped": flipped,
        "zero": zero,
        "average_stretch": average,
        "max_stretch": max(stretches, default=0.0),
        "problem_count": sum(value > stretch_threshold for value in stretches),
        "summed_uv_area": summed_uv_area,
        # Temporary compatibility alias for API users; this is not true union coverage.
        "coverage": summed_uv_area,
    }


def validate_object(obj, tolerance=1.0e-10, stretch_threshold=2.0):
    return validate_snapshot(
        build_uv_triangle_snapshot(obj), tolerance, stretch_threshold,
    )


def _inside(point, start, end, orientation, epsilon):
    cross = (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])
    return cross * orientation >= -epsilon


def _intersection(a, b, c, d):
    abx, aby, cdx, cdy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    denominator = abx * cdy - aby * cdx
    if abs(denominator) < 1.0e-15:
        return b
    factor = ((c[0] - a[0]) * cdy - (c[1] - a[1]) * cdx) / denominator
    return a[0] + factor * abx, a[1] + factor * aby


def _clipped_polygon(subject, clip, epsilon):
    output = list(subject)
    orientation = 1.0 if polygon_area_2d(clip) >= 0.0 else -1.0
    for index, start in enumerate(clip):
        end, input_points, output = clip[(index + 1) % len(clip)], output, []
        if not input_points:
            break
        previous = input_points[-1]
        previous_inside = _inside(previous, start, end, orientation, epsilon)
        for current in input_points:
            current_inside = _inside(current, start, end, orientation, epsilon)
            if current_inside:
                if not previous_inside:
                    output.append(_intersection(previous, current, start, end))
                output.append(current)
            elif previous_inside:
                output.append(_intersection(previous, current, start, end))
            previous, previous_inside = current, current_inside
    return output


def _bbox_overlaps(a, b, epsilon):
    return not (a[2] <= b[0] + epsilon or b[2] <= a[0] + epsilon
                or a[3] <= b[1] + epsilon or b[3] <= a[1] + epsilon)


def _triangles_overlap_with_area(a, b, area_epsilon, coord_epsilon):
    return abs(polygon_area_2d(_clipped_polygon(a, b, coord_epsilon))) > area_epsilon


def _candidate_pairs(records):
    """Yield unique broad-phase pairs using an adaptive spatial hash."""
    if len(records) < 2:
        return
    min_x = min(record.bbox[0] for record in records)
    min_y = min(record.bbox[1] for record in records)
    extent = max(max(record.bbox[2] for record in records) - min_x,
                 max(record.bbox[3] for record in records) - min_y, 1.0e-9)
    cell_size = extent / max(1, int(sqrt(len(records))))
    cells, seen = defaultdict(list), set()
    for index, record in enumerate(records):
        x0, x1 = floor((record.bbox[0] - min_x) / cell_size), floor((record.bbox[2] - min_x) / cell_size)
        y0, y1 = floor((record.bbox[1] - min_y) / cell_size), floor((record.bbox[3] - min_y) / cell_size)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for other in cells[(x, y)]:
                    pair = (other, index)
                    if pair not in seen:
                        seen.add(pair)
                        yield pair
                cells[(x, y)].append(index)


def find_overlaps(records, area_epsilon, coord_epsilon, across_objects=True):
    """Return overlapping ``(object name, face index)`` keys and pair count."""
    faces, pairs = set(), set()
    for index_a, index_b in _candidate_pairs(records):
        a, b = records[index_a], records[index_b]
        if a.obj == b.obj and a.face_index == b.face_index:
            continue
        if not across_objects and a.obj != b.obj:
            continue
        if not _bbox_overlaps(a.bbox, b.bbox, coord_epsilon):
            continue
        if not _triangles_overlap_with_area(a.coordinates, b.coordinates, area_epsilon, coord_epsilon):
            continue
        keys = ((a.obj.name, a.face_index), (b.obj.name, b.face_index))
        pairs.add(tuple(sorted(keys)))
        faces.update(keys)
    return faces, len(pairs)
