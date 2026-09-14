"""UV validation and overlap geometry.

This module deliberately contains no operators or context manipulation.  All
UV intersection work lives here so it can be tested independently of Blender's
UI state.
"""
from __future__ import annotations
from collections import defaultdict
from math import floor
from math import sqrt
from typing import NamedTuple


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


def triangles_from_object(obj, area_epsilon: float) -> list[TriangleRecord]:
    """Return non-degenerate UV triangles using Blender's tessellation."""
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    if uv_layer is None:
        return []
    mesh.calc_loop_triangles()
    records = []
    for loop_triangle in mesh.loop_triangles:
        # Blender 5 exposes UV values through the layer's ``uv`` collection.
        triangle = tuple(tuple(uv_layer.uv[index].vector) for index in loop_triangle.loops)
        if abs(polygon_area_2d(triangle)) <= area_epsilon:
            continue
        xs, ys = zip(*triangle)
        records.append(TriangleRecord(obj, loop_triangle.polygon_index, triangle,
                                      (min(xs), min(ys), max(xs), max(ys))))
    return records


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

def signed_area(a,b,c): return ((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))*.5
def validate_object(obj, tolerance=1e-10, stretch_threshold=2.0):
    mesh=obj.data; uv=mesh.uv_layers.active
    if uv is None: raise RuntimeError("Active UV map required")
    mesh.calc_loop_triangles(); flipped=set(); zero=set(); stretches=[]; uv_area=0.0
    for tri in mesh.loop_triangles:
        points=[uv.uv[i].vector for i in tri.loops]; area=signed_area(*points)
        if area < -tolerance: flipped.add(tri.polygon_index)
        if abs(area) <= tolerance or any((points[i]-points[(i+1)%3]).length_squared <= tolerance for i in range(3)): zero.add(tri.polygon_index)
        a,b,c=(obj.matrix_world @ mesh.vertices[i].co for i in tri.vertices)
        area3=(b-a).cross(c-a).length*.5
        if area3 > tolerance and abs(area)>tolerance:
            ratio=abs(area)/area3; stretches.append(max(ratio,1.0/ratio))
        uv_area += abs(area)
    avg=sum(stretches)/len(stretches) if stretches else 0.0
    return {"flipped":flipped,"zero":zero,"average_stretch":avg,"max_stretch":max(stretches,default=0.0),"problem_count":sum(v>stretch_threshold for v in stretches),"coverage":uv_area}
