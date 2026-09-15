import importlib.util
import math
import sys
import types
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).parents[1] / "auto_seam_uv_equalizer"
package = sys.modules.setdefault("auto_seam_uv_equalizer", types.ModuleType("auto_seam_uv_equalizer"))
package.__path__ = [str(ROOT)]
for name in ("seam_path", "chart_seam"):
    spec = importlib.util.spec_from_file_location(f"auto_seam_uv_equalizer.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
chart_seam = sys.modules["auto_seam_uv_equalizer.chart_seam"]
analyze, face_adjacency, segment_faces = chart_seam.analyze, chart_seam.face_adjacency, chart_seam.segment_faces
candidate_benefit = chart_seam.candidate_benefit
uv_chart_quality = chart_seam.uv_chart_quality
shortest_path = sys.modules["auto_seam_uv_equalizer.seam_path"].shortest_path
continuity_penalty = sys.modules["auto_seam_uv_equalizer.seam_path"].continuity_penalty


class Vector:
    def __init__(self, x, y=0.0, z=0.0): self.xyz = (x, y, z)
    def __sub__(self, other): return Vector(*(a - b for a, b in zip(self.xyz, other.xyz)))
    def __iter__(self): return iter(self.xyz)
    @property
    def x(self): return self.xyz[0]
    @property
    def y(self): return self.xyz[1]
    def dot(self, other): return sum(a * b for a, b in zip(self.xyz, other.xyz))
    def cross(self, other):
        ax, ay, az = self.xyz; bx, by, bz = other.xyz
        return Vector(ay*bz-az*by, az*bx-ax*bz, ax*by-ay*bx)
    @property
    def length(self): return sum(value * value for value in self.xyz) ** .5


class Normal:
    def __init__(self, angle=0.0): self.value = angle
    def angle(self, other): return max(self.value, other.value)


def mesh(face_count=2, seam=False):
    vertices = [SimpleNamespace(co=Vector(index)) for index in range(4)]
    edges = [SimpleNamespace(index=0, vertices=(0, 1), use_seam=seam,
                             use_edge_sharp=False, is_convex=True)]
    faces = [SimpleNamespace(normal=Normal(), material_index=0) for _ in range(face_count)]
    return SimpleNamespace(vertices=vertices, edges=edges, polygons=faces)


def settings(**overrides):
    values = dict(seam_preset="ORGANIC", material_boundary=True,
                  preserve_existing_seams=True, chart_refinement_iterations=3,
                  max_chart_distortion=.2, seam_minimum_spacing=0,
                  seam_count_penalty=0.0, straightness_bias=.6,
                  seam_search_radius=24, curvature_bias=1.0,
                  weight_material=1.5)
    values.update(overrides)
    return SimpleNamespace(**values)


def test_face_graph_and_segmentation_use_shared_edges():
    graph = face_adjacency(mesh(), {0: [0, 1]})
    assert graph[0] == [(1, 0)]
    assert segment_faces(2, graph, set()) == [{0, 1}]
    assert segment_faces(2, graph, {0}) == [{0}, {1}]


def test_flat_plane_does_not_create_internal_seam():
    result = analyze(mesh(), {0: [0, 1]}, [False], [False], settings())
    assert result.pending_seams == set()
    assert len(result.charts) == 1


def test_force_wins_force_protect_conflict():
    result = analyze(mesh(), {0: [0, 1]}, [True], [True], settings())
    assert result.pending_seams == {0}
    assert result.protected_edges == set()


def test_protect_and_existing_seam_policy():
    protected = analyze(mesh(), {0: [0, 1]}, [False], [True], settings())
    assert protected.pending_seams == set()
    preserved = analyze(mesh(seam=True), {0: [0, 1]}, [False], [False], settings())
    assert preserved.pending_seams == {0}
    replaced = analyze(mesh(seam=True), {0: [0, 1]}, [False], [False],
                       settings(preserve_existing_seams=False))
    assert replaced.pending_seams == set()


def test_bad_chart_refinement_improves_injected_uv_quality():
    result = analyze(mesh(), {0: [0, 1]}, [False], [False], settings(seam_preset="HARD_SURFACE"),
                     lambda _chart, cuts: .8 if not cuts else .05)
    assert result.candidate_seams == {0}
    assert max(result.quality.values()) < .2
    assert result.iterations >= 1


def test_refinement_can_improve_two_independent_bad_charts():
    test_mesh = SimpleNamespace(
        vertices=[SimpleNamespace(co=Vector(i % 2, i // 2)) for i in range(8)],
        edges=[SimpleNamespace(index=i, vertices=(i * 2, i * 2 + 1), use_seam=False,
                               use_edge_sharp=False, is_convex=True) for i in range(2)],
        polygons=[SimpleNamespace(normal=Normal(), material_index=0) for _ in range(4)],
    )
    edge_faces = {0: [0, 1], 1: [2, 3]}
    result = analyze(
        test_mesh, edge_faces, [False] * 2, [False] * 2,
        settings(seam_preset="HARD_SURFACE", chart_refinement_iterations=4),
        lambda chart, _cuts: .8 if len(chart) > 1 else .05,
    )
    assert result.candidate_seams == {0, 1}
    assert len(result.charts) == 4
    assert max(result.quality.values()) < .2


def test_candidate_without_measured_improvement_is_rejected():
    result = analyze(mesh(), {0: [0, 1]}, [False], [False],
                     settings(seam_preset="HARD_SURFACE"),
                     lambda _chart, _cuts: 1.0)
    assert result.candidate_seams == set()
    assert result.pending_seams == set()


def test_actual_gain_must_exceed_new_edge_cost():
    assert candidate_benefit(.8, .4, 2, .1) == pytest.approx(.2)
    assert candidate_benefit(.8, .4, 20, .1) < 0.0
    assert candidate_benefit(1.0, 1.0, 1, 0.0) is None


def test_professional_prior_weight_tables_and_sparsity_are_monotonic():
    assert chart_seam.dihedral_prior(60) > chart_seam.dihedral_prior(30) > chart_seam.dihedral_prior(5)
    penalties = [chart_seam.garment_sparsity_penalty(value) for value in (.01, .03, .05)]
    assert penalties[0] < penalties[1] < penalties[2]


def test_professional_visibility_ordering():
    assert chart_seam.visibility_prior((1, 0, 0), "-Y") > chart_seam.visibility_prior((0, 1, 0), "-Y")
    assert chart_seam.visibility_prior((0, 1, 0), "-Y") > chart_seam.visibility_prior((0, -1, 0), "-Y")
    assert chart_seam.visibility_prior((0, .1, 0), "-Y", True) > chart_seam.visibility_prior((1, 0, 0), "-Y", True)


def test_preset_edge_penalties_reduce_benefit_in_declared_order():
    base = .1
    benefit = {
        name: candidate_benefit(.8, .4, 2, base * (1 + chart_seam.PRESETS[name].seam_penalty))
        for name in ("HARD_SURFACE", "ORGANIC", "MANUAL")
    }
    assert benefit["HARD_SURFACE"] > benefit["ORGANIC"] > benefit["MANUAL"]


def test_continuity_penalty_distinguishes_straight_right_and_uturn():
    assert continuity_penalty((1, 0, 0), (1, 0, 0), 1) == pytest.approx(0)
    assert continuity_penalty((1, 0, 0), (0, 1, 0), 1) == pytest.approx(math.pi / 2)
    assert continuity_penalty((1, 0, 0), (-1, 0, 0), 1) == pytest.approx(math.pi)


def test_uv_chart_quality_executes_and_returns_finite_value():
    test_mesh = SimpleNamespace(
        vertices=[SimpleNamespace(co=Vector(0, 0, 0)),
                  SimpleNamespace(co=Vector(1, 0, 0)),
                  SimpleNamespace(co=Vector(0, 1, 0))],
        loops=[SimpleNamespace(vertex_index=i) for i in range(3)],
        loop_triangles=[SimpleNamespace(polygon_index=0, loops=(0, 1, 2))],
        calc_loop_triangles=lambda: None,
    )
    uv_layer = SimpleNamespace(uv=[SimpleNamespace(vector=Vector(0, 0)),
                                   SimpleNamespace(vector=Vector(1, 0)),
                                   SimpleNamespace(vector=Vector(0, 1))])
    assert math.isfinite(uv_chart_quality(test_mesh, uv_layer, {0}))


def test_collapsed_uv_triangles_increase_quality_error_without_nan():
    test_mesh = SimpleNamespace(
        vertices=[SimpleNamespace(co=Vector(0, 0, 0)),
                  SimpleNamespace(co=Vector(1, 0, 0)),
                  SimpleNamespace(co=Vector(0, 1, 0))],
        loops=[SimpleNamespace(vertex_index=i) for i in range(3)],
        loop_triangles=[SimpleNamespace(polygon_index=0, loops=(0, 1, 2))],
        calc_loop_triangles=lambda: None,
    )
    regular = SimpleNamespace(uv=[SimpleNamespace(vector=Vector(0, 0)),
                                  SimpleNamespace(vector=Vector(1, 0)),
                                  SimpleNamespace(vector=Vector(0, 1))])
    collapsed = SimpleNamespace(uv=[SimpleNamespace(vector=Vector(0, 0)) for _ in range(3)])
    regular_quality = uv_chart_quality(test_mesh, regular, {0})
    collapsed_quality = uv_chart_quality(test_mesh, collapsed, {0})
    assert math.isfinite(collapsed_quality)
    assert collapsed_quality > regular_quality
    assert collapsed_quality >= chart_seam.COLLAPSE_WEIGHT


def test_closed_chart_bootstrap_proposes_a_continuous_path():
    test_mesh = SimpleNamespace(
        vertices=[SimpleNamespace(co=Vector(i, 0, 0)) for i in range(4)],
        edges=[SimpleNamespace(index=i, vertices=(i, i + 1), use_seam=False,
                               use_edge_sharp=False, is_convex=True) for i in range(3)],
        polygons=[SimpleNamespace(normal=Normal(), material_index=0) for _ in range(2)],
    )
    result = analyze(
        test_mesh, {index: [0, 1] for index in range(3)}, [False] * 3, [False] * 3,
        settings(seam_preset="HARD_SURFACE", chart_refinement_iterations=1),
        lambda chart, _cuts: .8 if len(chart) > 1 else .05,
    )
    assert result.candidate_seams == {0, 1, 2}


def test_one_refinement_round_can_improve_three_bad_charts():
    test_mesh = SimpleNamespace(
        vertices=[SimpleNamespace(co=Vector(i, 0)) for i in range(6)],
        edges=[SimpleNamespace(index=i, vertices=(i * 2, i * 2 + 1), use_seam=False,
                               use_edge_sharp=False, is_convex=True) for i in range(3)],
        polygons=[SimpleNamespace(normal=Normal(), material_index=0) for _ in range(6)],
    )
    result = analyze(
        test_mesh, {i: [i * 2, i * 2 + 1] for i in range(3)},
        [False] * 3, [False] * 3,
        settings(seam_preset="HARD_SURFACE", chart_refinement_iterations=1),
        lambda chart, _cuts: .8 if len(chart) > 1 else .05,
    )
    assert result.candidate_seams == {0, 1, 2}


def test_existing_seam_attraction_respects_preserve_setting():
    test_mesh = mesh(seam=True)
    edge = test_mesh.edges[0]
    faces = [0, 1]
    preset = chart_seam.PRESETS["ORGANIC"]
    preserved = chart_seam.edge_cut_cost(
        test_mesh, edge, faces, False, False, preset, settings())
    ignored = chart_seam.edge_cut_cost(
        test_mesh, edge, faces, False, False, preset,
        settings(preserve_existing_seams=False))
    assert ignored > preserved


def test_uv_state_cache_unwraps_once_per_unique_cut_state():
    calls = []
    evaluate = chart_seam.cached_uv_quality_evaluator(
        lambda cuts: calls.append(frozenset(cuts)) or tuple(cuts),
        lambda snapshot, chart: len(snapshot) + len(chart),
    )
    for chart_index in range(10):
        evaluate({chart_index}, {1, 2})
    assert len(calls) == 1

    for cuts in ({1}, {2}, {3}):
        evaluate({0}, cuts)
    assert len(calls) == 4  # The original state plus three new states.


def test_performance_fixture_reuses_states_across_chart_candidates():
    calls = []
    evaluate = chart_seam.cached_uv_quality_evaluator(
        lambda cuts: calls.append(frozenset(cuts)) or tuple(cuts),
        lambda snapshot, chart: len(snapshot) + len(chart),
    )
    charts = [{index} for index in range(10)]
    seam_states = [set(), *({candidate} for candidate in range(25))]
    for cuts in seam_states:
        for chart in charts:
            evaluate(chart, cuts)
    assert len(calls) == len(seam_states)


def test_direction_aware_dijkstra_avoids_equal_cost_zigzag():
    positions = [Vector(0, 0), Vector(1, 0), Vector(2, 0),
                 Vector(1, 1), Vector(1, -1), Vector(99), Vector(3, 0)]
    graph = {
        0: [(1, 0), (3, 3)], 1: [(0, 0), (2, 1)],
        2: [(1, 1), (6, 2)], 3: [(0, 3), (4, 4)],
        4: [(3, 4), (6, 5)], 6: [(2, 2), (4, 5)],
    }
    assert shortest_path(graph, [0], [6], lambda _edge: 1.0, positions=positions,
                         straightness_bias=2.0) == [0, 1, 2]


def _edge_mesh(vertex_coordinates, edge_vertices, face_count=2):
    return SimpleNamespace(
        vertices=[SimpleNamespace(co=Vector(*co)) for co in vertex_coordinates],
        edges=[SimpleNamespace(index=i, vertices=edge, use_seam=False,
                               use_edge_sharp=False, is_convex=True)
               for i, edge in enumerate(edge_vertices)],
        polygons=[SimpleNamespace(normal=Normal(), material_index=0)
                  for _ in range(face_count)],
    )


def test_professional_rejection_does_not_starve_geodesic_fallback():
    test_mesh = _edge_mesh([(i, 0, 0) for i in range(7)],
                           [(i, i + 1) for i in range(6)])
    edge_faces = {i: [0, 1] for i in range(6)}
    tried = []

    def quality(_chart, cuts):
        tried.append(frozenset(cuts))
        return .2 if len(cuts) >= 3 else 1.0

    result = analyze(
        test_mesh, edge_faces, [False] * 6, [False] * 6,
        settings(seam_preset="HARD_SURFACE", chart_refinement_iterations=1), quality,
        preferred_paths=tuple({i} for i in range(5)),
    )
    assert len(result.candidate_seams) >= 3
    assert any(len(cuts) >= 3 for cuts in tried)


def test_analyze_discards_seed_prior_when_ranking_completed_paths(monkeypatch):
    test_mesh = _edge_mesh([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
                           [(0, 1), (2, 3)])
    priorities = {0: 10.0, 1: 5.0}
    monkeypatch.setattr(chart_seam, "professional_edge_prior",
                        lambda _m, index, _f, _s, sleeve=False:
                        (priorities[index], (0.0, 0.0, 0.0, 0.0)))
    monkeypatch.setattr(chart_seam, "path_professional_prior",
                        lambda _m, path, _f, _s, visibility_override=None:
                        .5 if path == {0} else 3.0)
    monkeypatch.setattr(chart_seam, "shortest_path", lambda *_args, **_kwargs: [])
    trials = []

    def quality(_chart, cuts):
        if cuts:
            trials.append(frozenset(cuts))
            return .5
        return 1.0

    analyze(test_mesh, {0: [0, 1], 1: [0, 1]}, [False] * 2, [False] * 2,
            settings(chart_refinement_iterations=1), quality)
    # Both seeds enter the pool, but completed-path prior 3.0 ranks ahead of .5.
    assert trials[:2] == [frozenset({1}), frozenset({0})]


def test_seed_prefilter_does_not_leak_into_completed_path_rank():
    costs = {0: .4, 1: .4, 2: .4, 3: .4}
    # A may win a seed prefilter (3.0 versus 1.5), but only the full-path
    # priors participate after path construction.
    candidate_a = chart_seam.completed_path_rank({0, 1}, costs, .5)
    candidate_b = chart_seam.completed_path_rank({2, 3}, costs, 2.0)
    assert candidate_b < candidate_a


def test_generic_structural_and_ring_candidates_share_final_rank_scale():
    costs = {index: value for index, value in enumerate((.2, .6, .3, .5, .4, .4))}
    generic = chart_seam.completed_path_rank({0, 1}, costs, .7)
    structural = chart_seam.completed_path_rank({2, 3}, costs, .7)
    ring_column = chart_seam.completed_path_rank({4, 5}, costs, .7)
    assert generic == pytest.approx(structural)
    assert structural == pytest.approx(ring_column)
    assert chart_seam.completed_path_rank({4, 5}, costs, .7, True) == pytest.approx(
        ring_column - 1.0)


def test_material_boundary_closed_loop_is_one_structural_candidate():
    test_mesh = _edge_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
                           [(0, 1), (1, 2), (2, 3), (3, 0)])
    test_mesh.polygons[1].material_index = 1
    paths = chart_seam.structural_candidate_paths(
        test_mesh, {0, 1}, {i: [0, 1] for i in range(4)}, set(), set(), settings())
    assert paths == (frozenset({0, 1, 2, 3}),)
    result = analyze(test_mesh, {i: [0, 1] for i in range(4)}, [False] * 4,
                     [False] * 4, settings(chart_refinement_iterations=1),
                     lambda _chart, _cuts: 1.0)
    assert result.candidate_seams == set()


def test_sleeve_visibility_uses_topology_local_frame():
    centers = [(0, 2, 0), (1, 2, .1), (2, 2, .4)]
    offsets = [(0, -1, 0), (0, 0, 1), (0, 1, 0), (0, 0, -1)]
    coordinates = [tuple(c[i] + offset[i] for i in range(3))
                   for c in centers for offset in offsets]
    rings = tuple(tuple(range(r * 4, r * 4 + 4)) for r in range(3))
    edge_vertices = [(rings[r][column], rings[r + 1][column])
                     for column in range(4) for r in range(2)]
    test_mesh = _edge_mesh(coordinates, edge_vertices)
    scores = [chart_seam.topology_sleeve_visibility(
        test_mesh, {column * 2, column * 2 + 1}, rings, "Y", "+Z")
        for column in range(4)]
    assert scores[0] > scores[3] > scores[2] > scores[1]


def test_sleeve_parallel_mirror_axis_has_no_false_outer_bonus():
    centers = [(0, 2, 0), (1, 2, 0), (2, 2, 0)]
    coordinates = [(x, y + radial_y, z) for x, y, z in centers
                   for radial_y in (-1, 1)]
    rings = ((0, 1), (2, 3), (4, 5))
    test_mesh = _edge_mesh(coordinates, [(0, 2), (2, 4)])
    assert chart_seam.topology_sleeve_visibility(
        test_mesh, {0, 1}, rings, "X", "+Z") == 0.0


def test_sleeve_front_degenerate_still_uses_medial_projection():
    centers = [(0, 2, 0), (1, 2, 0), (2, 2, 0)]
    coordinates = [(x, y + radial_y, z) for x, y, z in centers
                   for radial_y in (-1, 1)]
    rings = ((0, 1), (2, 3), (4, 5))
    test_mesh = _edge_mesh(coordinates, [(0, 2), (2, 4)])
    assert chart_seam.topology_sleeve_visibility(
        test_mesh, {0, 1}, rings, "Y", "+X") == pytest.approx(.30)


def test_all_cylinder_columns_reach_professional_ranking(monkeypatch):
    test_mesh = _edge_mesh([(i, 0, 0) for i in range(16)],
                           [(i * 2, i * 2 + 1) for i in range(8)])
    edge_faces = {i: [0, 1] for i in range(8)}
    seen = []
    original = chart_seam.path_professional_prior

    def record(mesh_value, path, faces, setting_value, visibility_override=None):
        seen.append(frozenset(path))
        return original(mesh_value, path, faces, setting_value, visibility_override)

    monkeypatch.setattr(chart_seam, "path_professional_prior", record)
    analyze(test_mesh, edge_faces, [False] * 8, [False] * 8,
            settings(seam_preset="CYLINDER", chart_refinement_iterations=1),
            lambda _chart, _cuts: 1.0, preferred_paths=tuple({i} for i in range(8)))
    assert {frozenset({i}) for i in range(8)}.issubset(set(seen))


def test_mirror_centerline_and_protected_counterpart_are_not_pairs():
    assert chart_seam.mirror_pair_path({0}, {0: 0}, set()) == ({0}, False)
    assert chart_seam.mirror_pair_path({0}, {0: 1}, {1}) == ({0}, False)
    assert chart_seam.mirror_pair_path({0}, {0: 1}, set()) == ({0, 1}, True)


def test_mirror_pair_quality_rejects_when_either_side_worsens():
    graph = {0: [(1, 0)], 1: [(0, 0)], 2: [(3, 1)], 3: [(2, 1)]}
    charts = [{0, 1}, {2, 3}]
    edge_faces = {0: [0, 1], 1: [2, 3]}

    def quality(chart, cuts):
        if not cuts:
            return 1.0
        return .5 if chart <= {0, 1} else 1.2

    _affected, _before, _after, worsened = chart_seam.affected_chart_quality(
        charts, {0, 1}, edge_faces, set(), quality, graph, 4)
    assert worsened


def test_object_level_sparsity_and_manual_prior_multiplier(monkeypatch):
    # One cut in a 100-edge garment is 1%, regardless of the current chart size.
    assert chart_seam.garment_sparsity_penalty(1 / 100) == 0.0
    test_mesh = mesh()
    monkeypatch.setattr(chart_seam, "visibility_prior", lambda *_args, **_kwargs: .3)
    organic = chart_seam.professional_edge_prior(test_mesh, 0, [0, 1], settings())[0]
    manual = chart_seam.professional_edge_prior(
        test_mesh, 0, [0, 1], settings(seam_preset="MANUAL"))[0]
    assert manual == pytest.approx(organic * .25)


def test_hard_surface_and_manual_scale_entire_professional_prior(monkeypatch):
    test_mesh = mesh()
    test_mesh.polygons[1].material_index = 1
    test_mesh.polygons[1].normal = Normal(math.radians(60.0))
    monkeypatch.setattr(chart_seam, "visibility_prior", lambda *_args, **_kwargs: 0.0)
    organic = chart_seam.professional_edge_prior(test_mesh, 0, [0, 1], settings())[0]
    hard = chart_seam.professional_edge_prior(
        test_mesh, 0, [0, 1], settings(seam_preset="HARD_SURFACE"))[0]
    manual = chart_seam.professional_edge_prior(
        test_mesh, 0, [0, 1], settings(seam_preset="MANUAL"))[0]
    assert hard == pytest.approx(organic * .25)
    assert manual == pytest.approx(organic * .25)
