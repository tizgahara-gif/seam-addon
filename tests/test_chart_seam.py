import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace

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


class Vector:
    def __init__(self, x, y=0.0, z=0.0): self.xyz = (x, y, z)
    def __sub__(self, other): return Vector(*(a - b for a, b in zip(self.xyz, other.xyz)))
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
