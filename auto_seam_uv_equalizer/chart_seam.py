"""Chart-based seam planning.

This module deliberately does not write to a Blender mesh.  It builds an O(F+E)
face graph and returns a complete pending seam set which the operator may commit
transactionally after validation.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from heapq import heappop, heappush
from math import acos, degrees, log, pi, sqrt
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
DISTORTION_RESERVED_TRIALS = 2
MAX_DISTORTION_CLUSTERS = 2
SEED_POOL_LIMIT = 12
QUALITY_EPSILON = 1.0e-7
UV_EPSILON = 1.0e-12
COLLAPSE_WEIGHT = 2.0
PROFESSIONAL_PRESET_MULTIPLIER = {
    "ORGANIC": 1.0,
    "CYLINDER": 1.0,
    "HARD_SURFACE": .25,
    "MANUAL": .25,
}


def garment_sparsity_penalty(seam_ratio):
    """Soft v1 garment prior: free to 2%, gradual to 4%, then steep."""
    if seam_ratio <= .02:
        return 0.0
    if seam_ratio <= .04:
        return .5 * (seam_ratio - .02) / .02
    return .5 + (seam_ratio - .04) * 10.0


def dihedral_prior(angle_degrees):
    """Compressed, deliberately bounded Professional Garment Prior odds."""
    # Blender supplies radians; tolerate conversion noise at the declared bands.
    angle_degrees += 1.0e-9
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


def _vector(values):
    return tuple(float(value) for value in values)


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _normalized(value):
    length = sqrt(_dot(value, value))
    return tuple(component / length for component in value) if length > UV_EPSILON else None


def _axis_vector(axis):
    result = [0.0, 0.0, 0.0]
    result["XYZ".index(axis[-1])] = 1.0 if axis[0] == "+" else -1.0
    return tuple(result)


def topology_sleeve_visibility(mesh, path, rings, mirror_axis="X", front_axis="-Y"):
    """Average sleeve visibility in the tube frame recovered from ring topology."""
    if len(rings) < 2 or not path:
        return 0.0
    positions = [_vector(vertex.co) for vertex in mesh.vertices]
    centers = [tuple(sum(positions[v][axis] for v in ring) / len(ring) for axis in range(3))
               for ring in rings]
    path_vertices = {vertex for edge_index in path for vertex in mesh.edges[edge_index].vertices}
    front = _axis_vector(front_axis)
    mirror_component = "XYZ".index(mirror_axis)
    scores = []
    for index, (ring, center) in enumerate(zip(rings, centers)):
        candidates = [vertex for vertex in ring if vertex in path_vertices]
        if not candidates:
            continue
        point = tuple(sum(positions[v][axis] for v in candidates) / len(candidates)
                      for axis in range(3))
        radial = _normalized(_sub(point, center))
        tangent = _normalized(_sub(centers[min(index + 1, len(centers) - 1)],
                                   centers[max(index - 1, 0)]))
        if radial is None or tangent is None:
            continue
        centre_sign = center[mirror_component]
        centre_direction = [0.0, 0.0, 0.0]
        if abs(centre_sign) > UV_EPSILON:
            centre_direction[mirror_component] = -1.0 if centre_sign > 0.0 else 1.0
        projected_medial = _normalized(tuple(
            centre_direction[i] - tangent[i] * _dot(centre_direction, tangent)
            for i in range(3)))
        projected_front = _normalized(tuple(
            front[i] - tangent[i] * _dot(front, tangent) for i in range(3)))
        medial_dot = _dot(radial, projected_medial) if projected_medial is not None else None
        front_dot = _dot(radial, projected_front) if projected_front is not None else None
        if medial_dot is not None and (front_dot is None or abs(medial_dot) >= abs(front_dot)):
            scores.append(.30 if medial_dot >= 0.0 else .10)
        elif front_dot is not None:
            scores.append(0.0 if front_dot >= 0.0 else .20)
        else:
            scores.append(0.0)
    return sum(scores) / len(scores) if scores else 0.0


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
    existing = 1.50 if (settings.preserve_existing_seams and edge.use_seam) else 0.0
    multiplier = PROFESSIONAL_PRESET_MULTIPLIER.get(settings.seam_preset, .25)
    return multiplier * (material + dihedral + visibility + existing), \
        tuple(multiplier * value for value in (material, dihedral, visibility, existing))


def professional_prior_multiplier(seam_preset):
    """Scale the complete prior so presets do not selectively double-count features."""
    return PROFESSIONAL_PRESET_MULTIPLIER.get(seam_preset, .25)


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


def _uv_distortion_samples(mesh, uv_vectors, chart):
    """Extract the shared scale-normalized triangle measurements."""
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
                samples.append((area3, area2, points3, points2, triangle.polygon_index))
    if not samples:
        return [], 1.0
    scale = max(UV_EPSILON, sum(max(item[1], UV_EPSILON) for item in samples) /
                sum(item[0] for item in samples))
    measured = []
    for area3, area2, points3, points2, face_index in samples:
        uv_edges = [(points2[(vertex + 1) % 3] - points2[vertex]).length for vertex in range(3)]
        collapsed = area2 <= UV_EPSILON or min(uv_edges) <= UV_EPSILON
        errors = []
        if not collapsed:
            for vertex in range(3):
                a3, b3 = points3[(vertex + 1) % 3] - points3[vertex], points3[(vertex + 2) % 3] - points3[vertex]
                a2, b2 = points2[(vertex + 1) % 3] - points2[vertex], points2[(vertex + 2) % 3] - points2[vertex]
                c3 = max(-1., min(1., a3.dot(b3) / max(1e-12, a3.length * b3.length)))
                c2 = max(-1., min(1., a2.dot(b2) / max(1e-12, a2.length * b2.length)))
                errors.append(abs(acos(c3) - acos(c2)) / pi)
        measured.append((area3, area2, sum(errors) / 3.0 if errors else 0.0,
                         collapsed, face_index))
    return measured, scale


def uv_chart_quality_from_snapshot(mesh, uv_vectors, chart):
    """Measure chart distortion; the v0.7 aggregate formula is unchanged."""
    samples, scale = _uv_distortion_samples(mesh, uv_vectors, chart)
    if not samples:
        return 2.0
    area_error = sum(abs(log(max(item[1], UV_EPSILON) / item[0] / scale))
                     for item in samples) / len(samples)
    valid = [item[2] for item in samples if not item[3]]
    angular = sum(valid) / len(valid) if valid else 0.0
    collapsed = sum(item[3] for item in samples)
    # Area and angle are dimensionless; collapse is an explicit strong penalty.
    collapse_ratio = collapsed / len(samples)
    return (.55 * angular + .35 * area_error +
            .10 * min(2.0, area_error * area_error) + COLLAPSE_WEIGHT * collapse_ratio)


def uv_face_distortion_from_snapshot(mesh, uv_vectors, chart):
    """Return per-face guidance scores; these never enter final seam benefit."""
    samples, scale = _uv_distortion_samples(mesh, uv_vectors, chart)
    by_face = defaultdict(list)
    for area3, area2, angular, collapsed, face_index in samples:
        area_error = abs(log(max(area2, UV_EPSILON) / area3 / scale))
        score = (.55 * angular + .35 * area_error +
                 .10 * min(2.0, area_error * area_error) + COLLAPSE_WEIGHT * collapsed)
        by_face[face_index].append(score)
    return {face: sum(values) / len(values) for face, values in by_face.items()}


def uv_chart_quality(mesh, uv_layer, chart):
    """Measure chart quality directly from a Blender UV layer."""
    return uv_chart_quality_from_snapshot(
        mesh, [item.vector for item in uv_layer.uv], chart)


def cached_uv_analysis_evaluators(unwrap_snapshot, quality_from_snapshot,
                                  distortion_from_snapshot):
    """Share one unwrap snapshot cache between quality and face guidance."""
    uv_state_cache, quality_cache, distortion_cache = {}, {}, {}
    def snapshot(cuts):
        key = frozenset(cuts)
        if key not in uv_state_cache:
            uv_state_cache[key] = unwrap_snapshot(cuts)
        return key, uv_state_cache[key]
    def quality(chart, cuts):
        cuts_key, state = snapshot(cuts); key = (frozenset(chart), cuts_key)
        if key not in quality_cache:
            quality_cache[key] = quality_from_snapshot(state, chart)
        return quality_cache[key]
    def distortion(chart, cuts):
        cuts_key, state = snapshot(cuts); key = (frozenset(chart), cuts_key)
        if key not in distortion_cache:
            distortion_cache[key] = distortion_from_snapshot(state, chart)
        return distortion_cache[key]
    return quality, distortion


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


def distortion_hot_clusters(face_scores, graph, cuts, epsilon=QUALITY_EPSILON,
                            limit=MAX_DISTORTION_CLUSTERS):
    """Find deterministic localized P80 hot-face components."""
    if not face_scores:
        return []
    values = sorted(face_scores.values()); middle = values[len(values) // 2]
    if len(values) % 2 == 0:
        middle = (values[len(values)//2 - 1] + middle) * .5
    if max(values) - middle <= epsilon:
        return []
    p80 = values[min(len(values) - 1, max(0, int(.8 * (len(values) - 1))))]
    hot = {face for face, score in face_scores.items()
           if score >= p80 and score > middle + epsilon}
    clusters = []
    while hot:
        seed = min(hot); hot.remove(seed); component = {seed}; queue = deque((seed,))
        while queue:
            face = queue.popleft()
            for other, edge in graph.get(face, ()):
                if edge not in cuts and other in hot:
                    hot.remove(other); component.add(other); queue.append(other)
        clusters.append(component)
    clusters.sort(key=lambda cluster: (-max(face_scores[f] for f in cluster),
                                       -sum(face_scores[f] for f in cluster), min(cluster)))
    return clusters[:limit]


def select_trial_paths(standard_paths, distortion_paths, limit=TRIAL_CANDIDATE_LIMIT,
                       reserved_distortion=DISTORTION_RESERVED_TRIALS):
    """Reserve guidance trial opportunities, deduplicating identical edge sets."""
    chosen, seen = [], set()
    def add(paths, maximum):
        for item in paths:
            key = frozenset(item[2])
            if key in seen: continue
            seen.add(key); chosen.append(item)
            if len(chosen) >= maximum: break
    add(sorted(distortion_paths, key=lambda item: item[:2]), min(limit, reserved_distortion))
    add(sorted(standard_paths, key=lambda item: item[:2]), limit)
    return chosen[:limit]


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


def structural_candidate_paths(mesh, chart, edge_faces, force_set, protect_set,
                               settings, minimum_length=2):
    """Return unbranched connected material/30-degree/Force structural chains."""
    selected = set()
    for index, faces in edge_faces.items():
        if (index in protect_set or len(faces) != 2 or
                not set(faces).issubset(chart)):
            continue
        polygons = [mesh.polygons[face] for face in faces]
        material = (settings.material_boundary and
                    polygons[0].material_index != polygons[1].material_index)
        high_dihedral = degrees(polygons[0].normal.angle(polygons[1].normal)) >= 30.0
        if material or high_dihedral or index in force_set:
            selected.add(index)
    vertex_edges = defaultdict(set)
    for index in selected:
        for vertex in mesh.edges[index].vertices:
            vertex_edges[vertex].add(index)
    components, unseen = [], set(selected)
    while unseen:
        todo, component = [unseen.pop()], set()
        while todo:
            edge_index = todo.pop()
            if edge_index in component:
                continue
            component.add(edge_index)
            neighbours = set().union(*(vertex_edges[v] for v in mesh.edges[edge_index].vertices))
            todo.extend(neighbours - component)
            unseen.difference_update(neighbours)
        degrees_by_vertex = defaultdict(int)
        for edge_index in component:
            for vertex in mesh.edges[edge_index].vertices:
                degrees_by_vertex[vertex] += 1
        # Degree <= 2 means exactly an open chain or closed loop, never a branch.
        if len(component) >= minimum_length and max(degrees_by_vertex.values(), default=0) <= 2:
            components.append(frozenset(component))
    return tuple(sorted(components, key=lambda path: (min(path), len(path))))


def path_professional_prior(mesh, path, edge_faces, settings, visibility_override=None):
    """Rank a completed path by the arithmetic mean of all its edge priors."""
    if not path:
        return 0.0
    values = [professional_edge_prior(mesh, index, edge_faces.get(index, ()), settings)[0]
              for index in path]
    if visibility_override is not None:
        # Replace the ordinary object-axis visibility component with the tube-frame score.
        ordinary = [professional_edge_prior(mesh, index, edge_faces.get(index, ()), settings)[1][2]
                    for index in path]
        override = professional_prior_multiplier(settings.seam_preset) * visibility_override
        values = [value - visibility + override
                  for value, visibility in zip(values, ordinary)]
    return sum(values) / len(values)


def completed_path_rank(path, costs, professional_prior, force_priority=False):
    """Rank a completed path without carrying its seed-prefilter score forward."""
    if not path:
        return float("inf")
    rank = sum(costs[index] for index in path) / len(path) - professional_prior
    return rank - (1.0 if force_priority else 0.0)


def mirror_pair_path(path, mirror_edges, protect_set):
    """Return an atomic pair, or the original path for self/partial/protected maps."""
    original = set(path)
    if not original or mirror_edges is None or not all(index in mirror_edges for index in original):
        return original, False
    mirrored = {mirror_edges[index] for index in original}
    if not any(mirror_edges[index] != index for index in original):
        return original, False
    if mirrored & protect_set:
        return original, False
    return original | mirrored, True


def affected_chart_quality(charts, split, edge_faces, cuts, evaluator, graph, face_count):
    """Aggregate both sides of an atomic mirror trial and reject any regression."""
    touched_faces = {face for edge in split for face in edge_faces.get(edge, ())}
    affected = [chart for chart in charts if chart & touched_faces]
    before_values = [evaluator(chart, cuts) for chart in affected]
    trial_cuts = cuts | split
    trial_charts = segment_faces(face_count, graph, trial_cuts)
    after_values = []
    for chart, before in zip(affected, before_values):
        descendants = [part for part in trial_charts if part.issubset(chart)]
        after = max((evaluator(part, trial_cuts) for part in descendants), default=before)
        if after > before + QUALITY_EPSILON:
            return affected, sum(before_values), sum(before_values), True
        after_values.append(after)
    return affected, sum(before_values), sum(after_values), False


def analyze(mesh, edge_faces, force, protect, settings, quality_evaluator=None,
            preferred_paths=(), mirror_edges=None, topology_rings=(),
            distortion_evaluator=None):
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
        claimed_charts = set()
        for chart in bad:
            if min(chart) in claimed_charts:
                continue
            best_trial = None
            ranked = []
            professional_paths = []
            distortion_paths = []
            professional = getattr(settings, "use_professional_garment_prior", True)
            sleeve = settings.seam_preset == "CYLINDER" and bool(preferred_paths)
            for path in preferred_paths:
                path = set(path)
                if path and not path & protect_set and path - cuts and all(
                        set(edge_faces.get(index, ())).issubset(chart) for index in path):
                    visibility = topology_sleeve_visibility(
                        mesh, path, topology_rings, getattr(settings, "mesh_symmetry_axis", "X"),
                        getattr(settings, "character_front_axis", "-Y")) if sleeve else None
                    score = path_professional_prior(
                        mesh, path, edge_faces, settings, visibility) if professional else 0.0
                    rank = completed_path_rank(path, costs, score, bool(path & force_set))
                    professional_paths.append((rank, min(path), path))
            if professional:
                for path in structural_candidate_paths(
                        mesh, chart, edge_faces, force_set, protect_set, settings,
                        max(2, min(3, settings.seam_minimum_spacing))):
                    if path - cuts:
                        score = path_professional_prior(mesh, path, edge_faces, settings)
                        professional_paths.append((
                            completed_path_rank(path, costs, score), min(path), set(path)))
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
            if (getattr(settings, "use_distortion_guided_candidates", True) and
                    distortion_evaluator is not None and chart_anchors):
                scores = distortion_evaluator(chart, cuts)
                for cluster in distortion_hot_clusters(scores, graph, cuts):
                    boundary = []
                    incident = []
                    for edge_index, faces in edge_faces.items():
                        if (len(faces) != 2 or not set(faces).issubset(chart) or
                                edge_index in cuts or edge_index in protect_set):
                            continue
                        if min(distance.get(faces[0], 10**9), distance.get(faces[1], 10**9)) < max(settings.seam_minimum_spacing, preset.spacing):
                            continue
                        hot_count = sum(face in cluster for face in faces)
                        if not hot_count:
                            continue
                        edge = mesh.edges[edge_index]
                        length = (mesh.vertices[edge.vertices[0]].co - mesh.vertices[edge.vertices[1]].co).length
                        prior = professional_edge_prior(mesh, edge_index, faces, settings, sleeve)[0] if professional else 0.0
                        item = (-max(scores.get(face, 0.0) for face in faces),
                                costs[edge_index] + length * .01 - prior, edge_index)
                        (boundary if hot_count == 1 else incident).append(item)
                    pool = boundary or incident
                    if not pool:
                        continue
                    chosen = min(pool)[2]; seed = mesh.edges[chosen]
                    path = shortest_path(vertex_graph, seed.vertices, anchors - set(seed.vertices),
                                         lambda index: costs.get(index, 1.0), settings.seam_search_radius,
                                         [vertex.co for vertex in mesh.vertices],
                                         settings.straightness_bias * preset.straightness)
                    split = {chosen, *path}
                    if split - cuts and not split & protect_set:
                        score = path_professional_prior(mesh, split, edge_faces, settings) if professional else 0.0
                        distortion_paths.append((completed_path_rank(split, costs, score), chosen, split))
            # Tier 2 is deliberately kept separate: professional candidates can
            # never starve a closed-chart geodesic fallback.
            bootstrap = set()
            if not chart_anchors:
                bootstrap = closed_chart_bootstrap_path(
                    mesh, chart, edge_faces, vertex_graph, costs,
                    settings.seam_search_radius,
                    settings.straightness_bias * preset.straightness)
            for _seed_prefilter_rank, chosen in sorted(ranked)[:SEED_POOL_LIMIT]:
                seed = mesh.edges[chosen]
                path = shortest_path(vertex_graph, seed.vertices, anchors - set(seed.vertices),
                                     lambda index: costs.get(index, 1.0), settings.seam_search_radius,
                                     [vertex.co for vertex in mesh.vertices],
                                     settings.straightness_bias * preset.straightness)
                split = {chosen, *path}
                path_prior = path_professional_prior(mesh, split, edge_faces, settings) if professional else 0.0
                professional_paths.append((
                    completed_path_rank(split, costs, path_prior), chosen, split))

            if professional and mirror_edges is not None:
                professional_paths = [
                    (rank - (1.0 if mirror_pair_path(path, mirror_edges, protect_set)[1] else 0.0),
                     chosen, path)
                    for rank, chosen, path in professional_paths
                ]

            def try_paths(paths):
                nonlocal best_trial
                for _rank, chosen, original_split in paths:
                    split, is_pair = mirror_pair_path(
                        original_split, mirror_edges if professional else None, protect_set)
                    # Non-paired candidates may discard only their own protected
                    # edges; protected counterparts never create a partial pair.
                    if not is_pair:
                        split.difference_update(protect_set)
                    new_edges = split - cuts
                    if not new_edges:
                        continue
                    if is_pair:
                        affected, before_trial, after, worsened = affected_chart_quality(
                            charts, new_edges, edge_faces, cuts, evaluator, graph,
                            len(mesh.polygons))
                        if worsened:
                            continue
                    else:
                        affected = [chart]
                        before_trial = before
                        trial_cuts = cuts | new_edges
                        trial_charts = segment_faces(len(mesh.polygons), graph, trial_cuts)
                        descendants = [part for part in trial_charts if part.issubset(chart)]
                        after = max((evaluator(part, trial_cuts) for part in descendants),
                                    default=before_trial)
                    eligible_edges = {index for index, faces in edge_faces.items() if len(faces) == 2}
                    seam_ratio = len((cuts | new_edges) & eligible_edges) / max(1, len(eligible_edges))
                    sparse = (garment_sparsity_penalty(seam_ratio)
                              if professional and settings.seam_preset in {"ORGANIC", "CYLINDER"}
                              else 0.0)
                    if settings.seam_preset == "CYLINDER":
                        sparse *= .5
                    benefit = candidate_benefit(
                        before_trial, after, len(new_edges), effective_edge_penalty, sparse)
                    if benefit is None or benefit <= QUALITY_EPSILON:
                        continue
                    candidate = (benefit, -len(new_edges), new_edges,
                                 {min(item) for item in affected})
                    if best_trial is None or candidate[:2] > best_trial[:2]:
                        best_trial = candidate

            tier_one = select_trial_paths(professional_paths, distortion_paths)
            try_paths(tier_one)
            # Only if every Tier-1 trial failed and this closed chart has no
            # usable anchor do we measure the independent geodesic candidate.
            if best_trial is None and not chart_anchors and bootstrap - cuts:
                try_paths([(0.0, min(bootstrap), bootstrap)])
            if best_trial is not None:
                accepted_this_round.append(best_trial[2])
                claimed_charts.update(best_trial[3])
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
