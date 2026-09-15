"""Chart-based seam planning.

This module deliberately does not write to a Blender mesh.  It builds an O(F+E)
face graph and returns a complete pending seam set which the operator may commit
transactionally after validation.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from heapq import heappop, heappush
from math import acos, degrees, log, pi
from .seam_path import shortest_path


@dataclass(frozen=True)
class ChartPreset:
    dihedral: float
    material: float
    sharp: float
    existing: float
    threshold: float
    seam_penalty: float
    spacing: int
    straightness: float
    iterations: int
    method: str


PRESETS = {
    "HARD_SURFACE": ChartPreset(2.4, 2.0, 2.5, 2.0, .72, .18, 1, 1.4, 4, "CONFORMAL"),
    "ORGANIC": ChartPreset(.75, 1.0, .35, 2.0, .88, .55, 4, .65, 5, "ANGLE_BASED"),
    "CYLINDER": ChartPreset(.45, .6, .25, 2.0, .92, .42, 3, 1.8, 5, "ANGLE_BASED"),
    "MANUAL": ChartPreset(.2, .4, .2, 3.0, .96, .8, 5, 1.0, 3, "ANGLE_BASED"),
}

TRIAL_CANDIDATE_LIMIT = 5
QUALITY_EPSILON = 1.0e-7
UV_EPSILON = 1.0e-12
COLLAPSE_WEIGHT = 2.0


def garment_sparsity_penalty(seam_ratio):
    """Soft v1 garment prior: free to 2%, gradual to 4%, then steep."""
    if seam_ratio <= .02:
        return 0.0
    if seam_ratio <= .04:
        return .5 * (seam_ratio - .02) / .02
    return .5 + (seam_ratio - .04) * 10.0


def dihedral_prior(angle_degrees):
    """Compressed, deliberately bounded Professional Garment Prior odds."""
    if angle_degrees < 5.0:
        return 0.0
    if angle_degrees < 15.0:
        return .60
    if angle_degrees < 30.0:
        return .65
    if angle_degrees < 60.0:
        return 1.40
    return 2.0


def candidate_benefit(before, after, new_edge_count, effective_edge_penalty,
                      sparsity_penalty=0.0):
    """Return measured gain minus the price of newly added seam edges."""
    if after >= before - QUALITY_EPSILON:
        return None
    return before - after - new_edge_count * effective_edge_penalty - sparsity_penalty


def _front_components(co, front_axis):
    axis = front_axis[-1]
    sign = 1.0 if front_axis[0] == "+" else -1.0
    values = tuple(co)
    x, y = values[:2]
    front = sign * (x if axis == "X" else y)
    side = y if axis == "X" else x
    return front, side


def visibility_prior(co, front_axis="-Y", sleeve=False):
    """Classify an object-local candidate midpoint without a world BBox."""
    front, side = _front_components(co, front_axis)
    if sleeve:
        # Near the bilateral centre is inner; lateral-facing is outer.
        if abs(side) < abs(front):
            return .30 if abs(side) <= abs(front) * .5 else .10
        return .20 if front < 0.0 else 0.0
    if abs(side) >= abs(front):
        return .35
    return .30 if front < 0.0 else 0.0


def professional_edge_prior(mesh, edge_index, faces, settings, sleeve=False):
    """Return ranking-only prior components for one manifold edge."""
    edge = mesh.edges[edge_index]
    polygons = [mesh.polygons[index] for index in faces]
    material = 2.20 if (len(polygons) == 2 and settings.material_boundary and
                        polygons[0].material_index != polygons[1].material_index) else 0.0
    angle = degrees(polygons[0].normal.angle(polygons[1].normal)) if len(polygons) == 2 else 0.0
    dihedral = dihedral_prior(angle)
    endpoints = [tuple(mesh.vertices[index].co) for index in edge.vertices]
    midpoint = tuple((a + b) * .5 for a, b in zip(*endpoints))
    visibility = visibility_prior(midpoint, getattr(settings, "character_front_axis", "-Y"), sleeve)
    if settings.seam_preset == "HARD_SURFACE":
        visibility *= .1
    elif settings.seam_preset == "MANUAL":
        visibility *= .25
    existing = 1.50 if (settings.preserve_existing_seams and edge.use_seam) else 0.0
    return material + dihedral + visibility + existing, (material, dihedral, visibility, existing)


@dataclass
class ChartAnalysis:
    signature: tuple
    charts: list[set[int]]
    problem_charts: list[set[int]]
    candidate_seams: set[int]
    pending_seams: set[int]
    protected_edges: set[int]
    force_edges: set[int]
    cut_costs: dict[int, float]
    quality: dict[int, float]
    iterations: int = 0


def face_adjacency(mesh, edge_faces):
    """Return face neighbours as ``(other_face, edge_index)`` pairs."""
    graph = defaultdict(list)
    for edge_index, faces in edge_faces.items():
        if len(faces) == 2:
            a, b = faces
            graph[a].append((b, edge_index))
            graph[b].append((a, edge_index))
    return graph


def edge_cut_cost(mesh, edge, faces, force, protect, preset, settings):
    """Cost in [0, 1]: low values are desirable cuts; Force wins conflicts."""
    if force:
        return 0.0
    if protect:
        return float("inf")
    if len(faces) != 2:                 # open/non-manifold is already a boundary
        return 0.0
    a, b = (mesh.polygons[index] for index in faces)
    angle = min(pi, a.normal.angle(b.normal)) / pi
    material = float(a.material_index != b.material_index and settings.material_boundary)
    sharp = float(getattr(edge, "use_edge_sharp", False))
    existing = (float(getattr(edge, "use_seam", False))
                if settings.preserve_existing_seams else 0.0)
    concavity = .12 if getattr(edge, "is_convex", True) is False else 0.0
    desirability = (preset.dihedral * settings.curvature_bias * angle +
                    preset.material * settings.weight_material * material +
                    preset.sharp * sharp + preset.existing * existing + concavity)
    return 1.0 / (1.0 + desirability)


def segment_faces(face_count, graph, cuts):
    """Connected components of the dual graph after removing cut edges."""
    unseen, charts = set(range(face_count)), []
    while unseen:
        root = unseen.pop(); chart = {root}; queue = deque((root,))
        while queue:
            face = queue.popleft()
            for other, edge in graph.get(face, ()):
                if edge not in cuts and other in unseen:
                    unseen.remove(other); chart.add(other); queue.append(other)
        charts.append(chart)
    return charts


def proxy_chart_quality(mesh, chart, edge_faces):
    """Scale-independent pre-unwrap curvature/stretch proxy.

    Actual operators replace this value with UV area and angular distortion
    measured on a temporary Blender unwrap.  The proxy keeps the backend useful
    for validation and headless unit tests and never treats a flat chart as bad.
    """
    angles = []
    for faces in edge_faces.values():
        if len(faces) == 2 and faces[0] in chart and faces[1] in chart:
            angles.append(mesh.polygons[faces[0]].normal.angle(mesh.polygons[faces[1]].normal) / pi)
    if not angles:
        return 0.0
    mean = sum(angles) / len(angles)
    accumulated = sum(value * value for value in angles) ** .5
    return min(2.0, .55 * mean + .45 * accumulated)


def uv_chart_quality_from_snapshot(mesh, uv_vectors, chart):
    """Measure chart distortion from a sequence indexed by mesh-loop index."""
    samples = []
    mesh.calc_loop_triangles()
    for triangle in mesh.loop_triangles:
        if triangle.polygon_index in chart:
            tri = triangle.loops
            points3 = [mesh.vertices[mesh.loops[index].vertex_index].co for index in tri]
            points2 = [uv_vectors[index] for index in tri]
            area3 = (points3[1] - points3[0]).cross(points3[2] - points3[0]).length * .5
            u = points2[1] - points2[0]; v = points2[2] - points2[0]
            area2 = abs(u.x * v.y - u.y * v.x) * .5
            if area3 > UV_EPSILON:
                samples.append((area3, area2, points3, points2))
    if not samples:
        return 2.0
    scale = max(UV_EPSILON, sum(max(item[1], UV_EPSILON) for item in samples) /
                sum(item[0] for item in samples))
    area_error = sum(abs(log(max(item[1], UV_EPSILON) / item[0] / scale))
                     for item in samples) / len(samples)
    angular = 0.0; angular_count = 0; collapsed = 0
    for _a3, _a2, p3, p2 in samples:
        uv_edges = [(p2[(vertex + 1) % 3] - p2[vertex]).length for vertex in range(3)]
        if _a2 <= UV_EPSILON or min(uv_edges) <= UV_EPSILON:
            collapsed += 1
            continue
        errors = []
        for vertex in range(3):
            a3, b3 = p3[(vertex + 1) % 3] - p3[vertex], p3[(vertex + 2) % 3] - p3[vertex]
            a2, b2 = p2[(vertex + 1) % 3] - p2[vertex], p2[(vertex + 2) % 3] - p2[vertex]
            c3 = max(-1., min(1., a3.dot(b3) / max(1e-12, a3.length * b3.length)))
            c2 = max(-1., min(1., a2.dot(b2) / max(1e-12, a2.length * b2.length)))
            errors.append(abs(acos(c3) - acos(c2)) / pi)
        angular += sum(errors) / 3.0
        angular_count += 1
    angular = angular / angular_count if angular_count else 0.0
    # Area and angle are dimensionless; collapse is an explicit strong penalty.
    collapse_ratio = collapsed / len(samples)
    return (.55 * angular + .35 * area_error +
            .10 * min(2.0, area_error * area_error) + COLLAPSE_WEIGHT * collapse_ratio)


def uv_chart_quality(mesh, uv_layer, chart):
    """Measure chart quality directly from a Blender UV layer."""
    return uv_chart_quality_from_snapshot(
        mesh, [item.vector for item in uv_layer.uv], chart)


def cached_uv_quality_evaluator(unwrap_snapshot, quality_from_snapshot):
    """Cache unwrap snapshots per cut state and qualities per chart/state pair."""
    uv_state_cache, quality_cache = {}, {}

    def evaluate(chart, cuts):
        cuts_key = frozenset(cuts)
        if cuts_key not in uv_state_cache:
            uv_state_cache[cuts_key] = unwrap_snapshot(cuts)
        key = (frozenset(chart), cuts_key)
        if key not in quality_cache:
            quality_cache[key] = quality_from_snapshot(
                uv_state_cache[cuts_key], chart)
        return quality_cache[key]

    return evaluate


def _geodesic_farthest(vertex_graph, positions, start, allowed_edges):
    """Return the farthest reachable vertex using 3D edge lengths."""
    distances, heap = {start: 0.0}, [(0.0, start)]
    while heap:
        distance, vertex = heappop(heap)
        if distance != distances.get(vertex):
            continue
        for neighbour, edge_index in vertex_graph.get(vertex, ()):
            if edge_index not in allowed_edges:
                continue
            length = (positions[vertex] - positions[neighbour]).length
            new_distance = distance + max(UV_EPSILON, length)
            if new_distance < distances.get(neighbour, float("inf")):
                distances[neighbour] = new_distance
                heappush(heap, (new_distance, neighbour))
    return max(distances, key=lambda vertex: (distances[vertex], -vertex))


def closed_chart_bootstrap_path(mesh, chart, edge_faces, vertex_graph, costs,
                                max_hops, straightness_bias):
    """Build a double-sweep geodesic seam path for a chart without anchors."""
    allowed = {index for index, faces in edge_faces.items()
               if faces and set(faces).issubset(chart) and costs.get(index) != float("inf")}
    vertices = {vertex for index in allowed for vertex in mesh.edges[index].vertices}
    if not vertices:
        return set()
    positions = [vertex.co for vertex in mesh.vertices]
    first = _geodesic_farthest(vertex_graph, positions, min(vertices), allowed)
    second = _geodesic_farthest(vertex_graph, positions, first, allowed)
    return set(shortest_path(
        vertex_graph, [first], [second],
        lambda index: costs.get(index, float("inf")) if index in allowed else float("inf"),
        max_hops, positions, straightness_bias))


def _edge_distance(graph, sources, limit):
    face_distance, queue = {}, deque()
    for face, neighbours in graph.items():
        if any(edge in sources for _, edge in neighbours):
            face_distance[face] = 0; queue.append(face)
    while queue:
        face = queue.popleft()
        if face_distance[face] >= limit:
            continue
        for other, _edge in graph.get(face, ()):
            if other not in face_distance:
                face_distance[other] = face_distance[face] + 1; queue.append(other)
    return face_distance


def analyze(mesh, edge_faces, force, protect, settings, quality_evaluator=None,
            preferred_paths=(), mirror_edges=None):
    """Build/refine provisional charts and return seams without mutating *mesh*."""
    preset = PRESETS.get(settings.seam_preset, PRESETS["HARD_SURFACE"])
    effective_edge_penalty = settings.seam_count_penalty * (1.0 + preset.seam_penalty)
    graph = face_adjacency(mesh, edge_faces)
    vertex_graph = defaultdict(list)
    for edge in mesh.edges:
        a, b = edge.vertices
        vertex_graph[a].append((b, edge.index)); vertex_graph[b].append((a, edge.index))
    force_set = {i for i, value in enumerate(force) if value}  # Force > Protect.
    protect_set = {i for i, value in enumerate(protect) if value and i not in force_set}
    existing = {edge.index for edge in mesh.edges if edge.use_seam} if settings.preserve_existing_seams else set()
    costs = {edge.index: edge_cut_cost(mesh, edge, edge_faces.get(edge.index, ()),
                                      edge.index in force_set, edge.index in protect_set,
                                      preset, settings) for edge in mesh.edges}
    cuts = set(existing) | force_set
    # Strong semantic boundaries seed charts; gentle organic curvature does not.
    cuts.update(i for i, cost in costs.items() if cost < (1.0 - preset.threshold) and i not in protect_set)
    candidates, qualities, bad = set(), {}, []
    evaluator = quality_evaluator or (lambda chart, _cuts: proxy_chart_quality(mesh, chart, edge_faces))
    iterations = min(settings.chart_refinement_iterations, preset.iterations)
    completed_iterations = 0
    for iteration in range(iterations + 1):
        charts = segment_faces(len(mesh.polygons), graph, cuts)
        qualities = {min(chart): evaluator(chart, cuts) for chart in charts}
        bad = [chart for chart in charts if qualities[min(chart)] > settings.max_chart_distortion]
        if not bad or iteration == iterations:
            break
        progressed = False
        distance = _edge_distance(graph, cuts, max(settings.seam_minimum_spacing, preset.spacing))
        # Every disjoint bad chart may contribute one candidate to this round.
        accepted_this_round = []
        for chart in bad:
            best_trial = None
            ranked = []
            trial_paths = []
            professional = getattr(settings, "use_professional_garment_prior", True)
            sleeve = settings.seam_preset == "CYLINDER" and bool(preferred_paths)
            for path in preferred_paths:
                path = set(path)
                if path and path - cuts and all(
                        set(edge_faces.get(index, ())).issubset(chart) for index in path):
                    score = sum(professional_edge_prior(mesh, i, edge_faces.get(i, ()), settings, sleeve)[0]
                                for i in path) / len(path) if professional else 0.0
                    trial_paths.append((-score, min(path), path))
            for edge_index, faces in edge_faces.items():
                if len(faces) != 2 or not set(faces).issubset(chart) or edge_index in cuts or edge_index in protect_set:
                    continue
                if min(distance.get(faces[0], 10**9), distance.get(faces[1], 10**9)) < max(settings.seam_minimum_spacing, preset.spacing):
                    continue
                edge = mesh.edges[edge_index]
                length = (mesh.vertices[edge.vertices[0]].co - mesh.vertices[edge.vertices[1]].co).length
                prior = professional_edge_prior(mesh, edge_index, faces, settings, sleeve)[0] if professional else 0.0
                ranked.append((costs[edge_index] + length * .01 - prior, edge_index))
            before = qualities[min(chart)]
            anchors = {vertex for edge_index in cuts for vertex in mesh.edges[edge_index].vertices}
            anchors.update(vertex for edge_index, faces in edge_faces.items() if len(faces) != 2
                           for vertex in mesh.edges[edge_index].vertices)
            chart_anchors = {vertex for vertex in anchors if any(
                edge_index in {index for index, faces in edge_faces.items()
                               if set(faces).issubset(chart)}
                for _other, edge_index in vertex_graph.get(vertex, ()))}
            # Professional candidates are tried before the generic closed-chart
            # geodesic, which fills only spare space in the five-trial budget.
            if not chart_anchors:
                bootstrap = closed_chart_bootstrap_path(
                    mesh, chart, edge_faces, vertex_graph, costs,
                    settings.seam_search_radius,
                    settings.straightness_bias * preset.straightness)
                if bootstrap - cuts:
                    # Sort after all professional seeds; it enters the five-cut
                    # budget only when those candidates are insufficient.
                    trial_paths.append((float("inf"), min(bootstrap), bootstrap))
            for _rank, chosen in sorted(ranked)[:TRIAL_CANDIDATE_LIMIT]:
                seed = mesh.edges[chosen]
                path = shortest_path(vertex_graph, seed.vertices, anchors - set(seed.vertices),
                                     lambda index: costs.get(index, 1.0), settings.seam_search_radius,
                                     [vertex.co for vertex in mesh.vertices],
                                     settings.straightness_bias * preset.straightness)
                split = {chosen, *path}
                trial_paths.append((_rank, chosen, split))
            if professional and mirror_edges is not None:
                trial_paths = [
                    (rank - (1.0 if split and all(index in mirror_edges for index in split) else 0.0),
                     chosen, split)
                    for rank, chosen, split in trial_paths
                ]
            for _rank, chosen, split in sorted(trial_paths, key=lambda item: item[:2])[:TRIAL_CANDIDATE_LIMIT]:
                # Reuse the canonical symmetry backend's unambiguous edge map.
                # Full mappings become one atomic trial; partial mappings fall
                # back to the original candidate without forced symmetry.
                if professional and mirror_edges is not None:
                    mirrored = {mirror_edges[index] for index in split if index in mirror_edges}
                    if len(mirrored) == len(split):
                        split = split | mirrored
                split.difference_update(protect_set)
                new_edges = split - cuts
                if not new_edges:
                    continue
                trial_cuts = cuts | new_edges
                trial_charts = segment_faces(len(mesh.polygons), graph, trial_cuts)
                descendants = [part for part in trial_charts if part.issubset(chart)]
                after = max((evaluator(part, trial_cuts) for part in descendants), default=before)
                eligible_edges = {index for index, faces in edge_faces.items()
                                  if len(faces) == 2 and set(faces).issubset(chart)}
                seam_ratio = len((cuts | new_edges) & eligible_edges) / max(1, len(eligible_edges))
                sparse = (garment_sparsity_penalty(seam_ratio)
                          if professional and settings.seam_preset in {"ORGANIC", "CYLINDER"} else 0.0)
                benefit = candidate_benefit(
                    before, after, len(new_edges), effective_edge_penalty, sparse)
                if benefit is None or benefit <= QUALITY_EPSILON:
                    continue
                candidate = (benefit, -len(new_edges), new_edges)
                if best_trial is None or candidate[:2] > best_trial[:2]:
                    best_trial = candidate
            if best_trial is not None:
                accepted_this_round.append(best_trial[2])
        for accepted in accepted_this_round:
            cuts.update(accepted); candidates.update(accepted); progressed = True
        completed_iterations += 1
        if not progressed:
            break
    charts = segment_faces(len(mesh.polygons), graph, cuts)
    qualities = {min(chart): evaluator(chart, cuts) for chart in charts}
    bad = [chart for chart in charts if qualities[min(chart)] > settings.max_chart_distortion]
    return ChartAnalysis((len(mesh.vertices), len(mesh.edges), len(mesh.polygons)), charts, bad,
                         candidates | force_set, cuts, protect_set, force_set, costs,
                         qualities, completed_iterations)
