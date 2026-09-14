"""UV overlap geometry and spatial broad-phase utilities.

This module deliberately contains no operators or context manipulation, so the
geometry can be tested independently of Blender's UI state.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import floor, sqrt


@dataclass(frozen=True)
class TriangleRecord:
    obj: object
    face_index: int
    coordinates: tuple
    bbox: tuple[float, float, float, float]


def polygon_area_2d(points) -> float:
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    return area * 0.5


def bbox_from_triangle(triangle):
    return (
        min(point[0] for point in triangle),
        min(point[1] for point in triangle),
        max(point[0] for point in triangle),
        max(point[1] for point in triangle),
    )


def triangles_from_object(obj, area_epsilon: float) -> list[TriangleRecord]:
    """Build records from Blender's tessellated faces, including concave N-gons."""
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return []

    mesh.calc_loop_triangles()
    records = []
    for loop_triangle in mesh.loop_triangles:
        triangle = tuple(
            tuple(uv_layer.uv[loop_index].vector) for loop_index in loop_triangle.loops
        )
        if abs(polygon_area_2d(triangle)) > area_epsilon:
            records.append(
                TriangleRecord(
                    obj=obj,
                    face_index=loop_triangle.polygon_index,
                    coordinates=triangle,
                    bbox=bbox_from_triangle(triangle),
                )
            )
    return records


def _inside_clip(point, edge_start, edge_end, orientation, coord_epsilon):
    cross = (
        (edge_end[0] - edge_start[0]) * (point[1] - edge_start[1])
        - (edge_end[1] - edge_start[1]) * (point[0] - edge_start[0])
    )
    return cross * orientation >= -coord_epsilon


def _line_intersection_2d(a, b, c, d):
    abx, aby = b[0] - a[0], b[1] - a[1]
    cdx, cdy = d[0] - c[0], d[1] - c[1]
    denominator = abx * cdy - aby * cdx
    if abs(denominator) < 1.0e-15:
        return b
    t = ((c[0] - a[0]) * cdy - (c[1] - a[1]) * cdx) / denominator
    return a[0] + t * abx, a[1] + t * aby


def clipped_polygon(subject, clip, coord_epsilon):
    output = list(subject)
    orientation = 1.0 if polygon_area_2d(clip) >= 0.0 else -1.0
    for index, edge_start in enumerate(clip):
        edge_end = clip[(index + 1) % len(clip)]
        input_points, output = output, []
        if not input_points:
            break
        previous = input_points[-1]
        previous_inside = _inside_clip(previous, edge_start, edge_end, orientation, coord_epsilon)
        for current in input_points:
            current_inside = _inside_clip(current, edge_start, edge_end, orientation, coord_epsilon)
            if current_inside:
                if not previous_inside:
                    output.append(_line_intersection_2d(previous, current, edge_start, edge_end))
                output.append(current)
            elif previous_inside:
                output.append(_line_intersection_2d(previous, current, edge_start, edge_end))
            previous, previous_inside = current, current_inside
    return output


def triangles_overlap(triangle_a, triangle_b, area_epsilon, coord_epsilon):
    intersection = clipped_polygon(triangle_a, triangle_b, coord_epsilon)
    return abs(polygon_area_2d(intersection)) > area_epsilon


def bbox_overlaps(a, b, coord_epsilon):
    return not (
        a[2] <= b[0] + coord_epsilon
        or b[2] <= a[0] + coord_epsilon
        or a[3] <= b[1] + coord_epsilon
        or b[3] <= a[1] + coord_epsilon
    )


def _candidate_pairs(records):
    """Yield unique bbox candidates from an adaptive uniform spatial hash."""
    if len(records) < 2:
        return
    min_x = min(record.bbox[0] for record in records)
    min_y = min(record.bbox[1] for record in records)
    max_x = max(record.bbox[2] for record in records)
    max_y = max(record.bbox[3] for record in records)
    extent = max(max_x - min_x, max_y - min_y, 1.0e-9)
    cell_size = extent / max(1, int(sqrt(len(records))))
    cells = defaultdict(list)
    seen_pairs = set()

    for record_index, record in enumerate(records):
        x0 = floor((record.bbox[0] - min_x) / cell_size)
        x1 = floor((record.bbox[2] - min_x) / cell_size)
        y0 = floor((record.bbox[1] - min_y) / cell_size)
        y1 = floor((record.bbox[3] - min_y) / cell_size)
        for cell_x in range(x0, x1 + 1):
            for cell_y in range(y0, y1 + 1):
                bucket = cells[(cell_x, cell_y)]
                for other_index in bucket:
                    pair = (other_index, record_index)
                    if pair not in seen_pairs:
                        seen_pairs.add(pair)
                        yield pair
                bucket.append(record_index)


def find_overlaps(records, area_epsilon, coord_epsilon, across_objects=True):
    """Return overlapping face keys and unique source-face pair count."""
    overlap_faces = set()
    overlap_pairs = set()
    for index_a, index_b in _candidate_pairs(records):
        a, b = records[index_a], records[index_b]
        if a.obj == b.obj and a.face_index == b.face_index:
            continue
        if not across_objects and a.obj != b.obj:
            continue
        if not bbox_overlaps(a.bbox, b.bbox, coord_epsilon):
            continue
        if not triangles_overlap(a.coordinates, b.coordinates, area_epsilon, coord_epsilon):
            continue
        key_a = (a.obj.name, a.face_index)
        key_b = (b.obj.name, b.face_index)
        overlap_pairs.add(tuple(sorted((key_a, key_b))))
        overlap_faces.update((key_a, key_b))
    return overlap_faces, len(overlap_pairs)
