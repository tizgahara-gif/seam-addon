"""Mesh seam detection utilities for Auto Seam UV Equalizer."""

from __future__ import annotations

from collections import defaultdict, deque
from math import radians
from typing import DefaultDict
from .mesh_utils import build_edge_to_faces
from .constants import FORCE_SEAM_ATTRIBUTE, PROTECT_SEAM_ATTRIBUTE
from .chart_seam import analyze
from .symmetry import mirror_edge_map
from .ring_topology import TopologyError, analyze_ring_topology
from .uv_protection import protected_edge_indices, validate_protection_consistency


MIN_MESH_FACE_COUNT = 1
LONGITUDINAL_ALIGNMENT = 0.65
LONGITUDINAL_SIDE_TOLERANCE = 0.18

# Public adapter contract shared by chart-analysis callers. Keeping this list
# next to the consumer prevents lightweight configurations from silently
# drifting out of sync with ``analysis_signature``.
CHART_ANALYSIS_SETTING_NAMES = (
    "seam_preset", "max_chart_distortion", "seam_count_penalty",
    "seam_minimum_spacing", "straightness_bias", "preserve_existing_seams",
    "unwrap_method", "material_boundary", "curvature_bias", "weight_material",
    "seam_search_radius", "chart_refinement_iterations", "character_front_axis",
    "use_professional_garment_prior", "mesh_symmetry_axis",
    "mesh_symmetry_tolerance", "use_distortion_guided_candidates",
    "use_edge_loop_completion",
)


def mark_selected_region_boundary_seams(bm, include_open_boundaries: bool = True) -> tuple[int, int, int, int, int]:
    """Add seams around selected BMesh faces without changing any selection.

    Returns selected faces, boundary edges, newly marked seams, included open
    boundaries, and skipped non-manifold edges, in that order.
    """
    selected_face_count = sum(1 for face in bm.faces if face.select)
    boundary_edge_count = 0
    newly_marked_seam_count = 0
    open_boundary_count = 0
    skipped_non_manifold_edge_count = 0

    for edge in bm.edges:
        linked_faces = edge.link_faces
        linked_face_count = len(linked_faces)

        if linked_face_count >= 3:
            skipped_non_manifold_edge_count += 1
            continue

        is_boundary = False
        if linked_face_count == 2:
            is_boundary = linked_faces[0].select != linked_faces[1].select
        elif linked_face_count == 1 and include_open_boundaries and linked_faces[0].select:
            is_boundary = True
            open_boundary_count += 1

        if not is_boundary:
            continue

        boundary_edge_count += 1
        if not edge.seam:
            edge.seam = True
            newly_marked_seam_count += 1

    return (
        selected_face_count,
        boundary_edge_count,
        newly_marked_seam_count,
        open_boundary_count,
        skipped_non_manifold_edge_count,
    )


def clear_seams(mesh) -> int:
    """Clear all seam flags on a mesh and return the number of changed edges."""
    # Consistency validation needs an Object for UV connectivity and is
    # performed by operator entry points; this primitive still enforces the
    # immutable-edge barrier when used independently.
    cleared_count = 0
    protected = protected_edge_indices(mesh)
    for edge in mesh.edges:
        if edge.index in protected:
            continue
        if edge.use_seam:
            edge.use_seam = False
            cleared_count += 1
    mesh.update()
    return cleared_count


def _should_mark_two_face_edge(mesh, face_indices: list[int], threshold_radians: float, use_material_boundary: bool) -> bool:
    face_a = mesh.polygons[face_indices[0]]
    face_b = mesh.polygons[face_indices[1]]

    if face_a.normal.angle(face_b.normal) >= threshold_radians:
        return True

    if use_material_boundary and face_a.material_index != face_b.material_index:
        return True

    return False


def mark_auto_seams(
    obj,
    angle_threshold_degrees: float,
    use_material_boundary: bool,
    use_boundary_edges: bool,
    use_non_manifold_edges: bool,
) -> int:
    """Mark automatic seams on a mesh object and return the number of newly marked edges."""
    if obj is None or obj.type != "MESH":
        return 0

    mesh = obj.data
    mesh.update(calc_edges=True)

    if len(mesh.polygons) < MIN_MESH_FACE_COUNT:
        return 0

    threshold_radians = radians(angle_threshold_degrees)
    edge_to_faces = build_edge_to_faces(mesh)
    protected = protected_edge_indices(mesh, edge_to_faces)
    marked_count = 0

    for edge in mesh.edges:
        if edge.index in protected:
            continue
        face_indices = edge_to_faces.get(edge.index, [])
        face_count = len(face_indices)
        should_mark = False

        if face_count == 1:
            should_mark = use_boundary_edges
        elif face_count == 2:
            should_mark = _should_mark_two_face_edge(
                mesh,
                face_indices,
                threshold_radians,
                use_material_boundary,
            )
        elif face_count > 2:
            should_mark = use_non_manifold_edges

        if should_mark and not edge.use_seam:
            edge.use_seam = True
            marked_count += 1

    mesh.update()
    return marked_count


def _bool_edge_attribute(mesh, name: str) -> list[bool]:
    attribute = mesh.attributes.get(name)
    if attribute is None or attribute.domain != "EDGE" or attribute.data_type != "BOOLEAN":
        return [False] * len(mesh.edges)
    return [item.value for item in attribute.data]


def analyze_chart_seams(obj, settings, quality_evaluator=None, distortion_evaluator=None):
    """Return a non-destructive chart plan for an object."""
    mesh = obj.data
    if mesh.uv_layers.active is not None:
        validate_protection_consistency(obj)
    mesh.update(calc_edges=True)
    edge_faces = build_edge_to_faces(mesh)
    force = _bool_edge_attribute(mesh, FORCE_SEAM_ATTRIBUTE)
    protect = _bool_edge_attribute(mesh, PROTECT_SEAM_ATTRIBUTE)
    for index in protected_edge_indices(mesh, edge_faces):
        protect[index] = True
        force[index] = False  # Finished is a hard barrier and outranks Force.
    preferred_paths, topology_rings = (), ()
    if settings.seam_preset == "CYLINDER":
        try:
            grid = analyze_ring_topology(mesh)
            # Chart-Based compares every longitudinal column.  The dedicated
            # Ring / Strip operator retains its single choose_seam() workflow.
            preferred_paths = tuple(grid.column_edges)
            topology_rings = tuple(grid.rings)
        except TopologyError:
            pass  # Irregular cylinders deliberately fall back to chart analysis.
    mirror_edges = None
    if (getattr(settings, "use_professional_garment_prior", True) and
            settings.seam_preset in {"ORGANIC", "CYLINDER"}):
        mirror_edges, _ambiguous = mirror_edge_map(
            [tuple(vertex.co) for vertex in mesh.vertices],
            [tuple(edge.vertices) for edge in mesh.edges],
            "XYZ".index(getattr(settings, "mesh_symmetry_axis", "X")),
            getattr(settings, "mesh_symmetry_tolerance", 0.0001))
    result = analyze(mesh, edge_faces, force, protect, settings, quality_evaluator,
                     preferred_paths, mirror_edges, topology_rings, distortion_evaluator)
    result.signature = analysis_signature(obj, settings)
    return result


def analysis_signature(obj, settings):
    """Fingerprint every mesh state and setting that affects chart analysis."""
    mesh = obj.data
    force = _bool_edge_attribute(mesh, FORCE_SEAM_ATTRIBUTE)
    protect = _bool_edge_attribute(mesh, PROTECT_SEAM_ATTRIBUTE)
    return (
        tuple(tuple(vertex.co) for vertex in mesh.vertices),
        tuple(tuple(edge.vertices) for edge in mesh.edges),
        tuple(tuple(face.vertices) for face in mesh.polygons),
        tuple(edge.use_seam for edge in mesh.edges), tuple(force), tuple(protect),
        tuple(getattr(edge, "use_edge_sharp", False) for edge in mesh.edges),
        tuple(face.material_index for face in mesh.polygons),
        tuple((name, getattr(settings, name, True) if name in {
            "use_distortion_guided_candidates", "use_edge_loop_completion"}
               else getattr(settings, name)) for name in CHART_ANALYSIS_SETTING_NAMES),
    )


def apply_chart_seams(obj, result) -> int:
    """Validate and atomically commit a previously calculated seam plan."""
    mesh = obj.data
    # The caller validates the full analysis signature before commit.  Keep a
    # topology guard here so this lower-level API is safe in isolation too.
    signature = (len(mesh.vertices), len(mesh.edges), len(mesh.polygons))
    result_topology = (len(result.signature[0]), len(result.signature[1]), len(result.signature[2]))
    if signature != result_topology:
        raise ValueError("Mesh topology changed after seam analysis")
    original = [edge.use_seam for edge in mesh.edges]
    protected = protected_edge_indices(mesh)
    target = result.pending_seams
    before = sum(edge.use_seam for edge in mesh.edges)
    try:
        for edge in mesh.edges:
            if edge.index in protected:
                continue
            edge.use_seam = edge.index in target
        mesh.update()
    except Exception:
        for edge, value in zip(mesh.edges, original):
            edge.use_seam = value
        mesh.update()
        raise
    return max(0, sum(edge.use_seam for edge in mesh.edges) - before)


def _longest_bbox_axis(mesh) -> tuple[int, list[float], list[float]] | None:
    if not mesh.vertices:
        return None

    mins = [min(vertex.co[i] for vertex in mesh.vertices) for i in range(3)]
    maxs = [max(vertex.co[i] for vertex in mesh.vertices) for i in range(3)]
    extents = [maxs[i] - mins[i] for i in range(3)]
    longest_axis = max(range(3), key=lambda index: extents[index])

    if extents[longest_axis] <= 1.0e-6:
        return None

    return longest_axis, mins, extents


def _edge_axis_alignment(mesh, edge, axis: int) -> float:
    vert_a = mesh.vertices[edge.vertices[0]].co
    vert_b = mesh.vertices[edge.vertices[1]].co
    direction = vert_b - vert_a

    if direction.length <= 1.0e-6:
        return 0.0

    return abs(direction.normalized()[axis])


def _edge_side_score(mesh, edge, minor_axes: list[int], mins: list[float], extents: list[float]) -> float:
    midpoint = (mesh.vertices[edge.vertices[0]].co + mesh.vertices[edge.vertices[1]].co) * 0.5
    score = 0.0

    for axis in minor_axes:
        extent = extents[axis]
        if extent > 1.0e-6:
            score += (midpoint[axis] - mins[axis]) / extent

    return score


def _find_longitudinal_candidates(mesh, edge_to_faces: dict[int, list[int]], axis: int) -> list[int]:
    candidates = []
    protected = protected_edge_indices(mesh, edge_to_faces)
    for edge in mesh.edges:
        if edge.index in protected:
            continue
        if edge.use_seam:
            continue
        if len(edge_to_faces.get(edge.index, [])) != 2:
            continue
        if _edge_axis_alignment(mesh, edge, axis) >= LONGITUDINAL_ALIGNMENT:
            candidates.append(edge.index)
    return candidates


def _has_existing_longitudinal_seam(mesh, edge_to_faces: dict[int, list[int]], axis: int) -> bool:
    for edge in mesh.edges:
        if not edge.use_seam:
            continue
        if len(edge_to_faces.get(edge.index, [])) != 2:
            continue
        if _edge_axis_alignment(mesh, edge, axis) >= LONGITUDINAL_ALIGNMENT:
            return True
    return False


def _collect_connected_edge_strip(mesh, candidate_indices: set[int], seed_index: int, seed_score: float, minor_axes: list[int], mins: list[float], extents: list[float]) -> set[int]:
    vertex_to_edges: DefaultDict[int, list[int]] = defaultdict(list)
    for edge_index in candidate_indices:
        edge = mesh.edges[edge_index]
        vertex_to_edges[edge.vertices[0]].append(edge_index)
        vertex_to_edges[edge.vertices[1]].append(edge_index)

    strip = set()
    queue: deque[int] = deque([seed_index])

    while queue:
        edge_index = queue.popleft()
        if edge_index in strip:
            continue

        edge = mesh.edges[edge_index]
        score = _edge_side_score(mesh, edge, minor_axes, mins, extents)
        if abs(score - seed_score) > LONGITUDINAL_SIDE_TOLERANCE:
            continue

        strip.add(edge_index)
        for vertex_index in edge.vertices:
            for next_edge_index in vertex_to_edges[vertex_index]:
                if next_edge_index not in strip:
                    queue.append(next_edge_index)

    return strip


def mark_longitudinal_seam_helper(obj) -> int:
    """Heuristically add one lengthwise seam strip for cylindrical or cable-like meshes."""
    if obj is None or obj.type != "MESH":
        return 0

    mesh = obj.data
    mesh.update(calc_edges=True)

    if len(mesh.edges) == 0 or len(mesh.polygons) < MIN_MESH_FACE_COUNT:
        return 0

    bbox_data = _longest_bbox_axis(mesh)
    if bbox_data is None:
        return 0

    axis, mins, extents = bbox_data
    edge_to_faces = build_edge_to_faces(mesh)

    if _has_existing_longitudinal_seam(mesh, edge_to_faces, axis):
        return 0

    candidates = _find_longitudinal_candidates(mesh, edge_to_faces, axis)
    if not candidates:
        return 0

    minor_axes = [index for index in range(3) if index != axis]
    seed_index = min(
        candidates,
        key=lambda edge_index: _edge_side_score(mesh, mesh.edges[edge_index], minor_axes, mins, extents),
    )
    seed_score = _edge_side_score(mesh, mesh.edges[seed_index], minor_axes, mins, extents)
    strip = _collect_connected_edge_strip(mesh, set(candidates), seed_index, seed_score, minor_axes, mins, extents)

    marked_count = 0
    for edge_index in strip:
        edge = mesh.edges[edge_index]
        if not edge.use_seam:
            edge.use_seam = True
            marked_count += 1

    mesh.update()
    return marked_count
