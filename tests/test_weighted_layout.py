import importlib.util
import math
import sys
import types
from pathlib import Path


MODULE = Path(__file__).parents[1] / "auto_seam_uv_equalizer" / "weighted_layout.py"


def _load_primitives():
    # Extracting these dependency-free functions would duplicate production logic;
    # instead provide minimal package dependency stubs through the normal test setup.
    package = sys.modules.setdefault("auto_seam_uv_equalizer", types.ModuleType("auto_seam_uv_equalizer"))
    package.__path__ = [str(MODULE.parent)]
    island = types.ModuleType("auto_seam_uv_equalizer.island_tools"); island.find_uv_islands = lambda obj: []
    mesh = types.ModuleType("auto_seam_uv_equalizer.mesh_utils"); mesh.build_mesh_topology = lambda obj: ({}, {}, {}, {})
    sys.modules[island.__name__] = island; sys.modules[mesh.__name__] = mesh
    spec = importlib.util.spec_from_file_location("auto_seam_uv_equalizer.weighted_layout", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_surface_area_and_density_weighting():
    module = _load_primitives()
    _, _, weights = module.calculate_weights([4.0, 1.0], [4, 1], 0.0)
    assert math.isclose(weights[0] / weights[1], 4.0)
    _, _, weights = module.calculate_weights([1.0, 1.0], [100, 1600], 0.25)
    assert math.isclose(weights[1] / weights[0], 2.0)


def test_density_influence_zero():
    module = _load_primitives()
    _, _, weights = module.calculate_weights([2.0, 2.0], [1, 1000], 0.0)
    assert weights == [2.0, 2.0]


def test_world_polygon_areas_uses_loop_triangles_for_concave_ngon():
    module = _load_primitives()

    class Identity:
        def __matmul__(self, value):
            return value

    class Vec:
        def __init__(self, x, y, z=0.0):
            self.x, self.y, self.z = x, y, z
        def __sub__(self, other):
            return Vec(self.x - other.x, self.y - other.y, self.z - other.z)
        def cross(self, other):
            return Vec(self.y * other.z - self.z * other.y,
                       self.z * other.x - self.x * other.z,
                       self.x * other.y - self.y * other.x)
        @property
        def length(self):
            return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    # Concave arrow: a fan from vertex zero would overlap; Blender's supplied
    # tessellation covers it as three non-overlapping triangles (area 3).
    vertices = [(0, 0), (2, 0), (2, 2), (1, 1), (0, 2)]
    mesh = types.SimpleNamespace(
        vertices=[types.SimpleNamespace(co=Vec(*co)) for co in vertices],
        polygons=[object()],
        loop_triangles=[
            types.SimpleNamespace(vertices=(0, 1, 3), polygon_index=0),
            types.SimpleNamespace(vertices=(1, 2, 3), polygon_index=0),
            types.SimpleNamespace(vertices=(0, 3, 4), polygon_index=0),
        ],
        calc_loop_triangles=lambda: None,
    )
    obj = types.SimpleNamespace(data=mesh, matrix_world=Identity())
    assert module.world_polygon_areas(obj) == [3.0]


def test_density_normalization_is_clamped():
    module = _load_primitives()
    _, normalized, _ = module.calculate_weights([1.0, 1.0], [1, 1_000_000], 1.0)
    assert normalized == [module.DENSITY_MIN, module.DENSITY_MAX]


def test_importance_boxes_preserve_aspect_and_weight_area_ratio():
    module = _load_primitives()
    boxes = module.importance_boxes([4.0, 1.0], [10.0, 0.25])
    areas = [width * height for width, height in boxes]
    assert math.isclose(areas[0] / areas[1], 4.0)
    assert math.isclose(boxes[0][0] / boxes[0][1], 10.0)
    assert math.isclose(boxes[1][0] / boxes[1][1], 0.25)


def _assert_packing(module, weights, aspects, root=(0.0, 0.0, 1.0, 1.0), padding=0.0):
    rectangles, scale = module.pack_importance_boxes(weights, aspects, root, padding)
    assert scale > 0.0 and math.isfinite(scale)
    for index, (x0, y0, x1, y1) in enumerate(rectangles):
        assert root[0] <= x0 < x1 <= root[2]
        assert root[1] <= y0 < y1 <= root[3]
        assert math.isclose((x1 - x0) / (y1 - y0), aspects[index], rel_tol=1e-9)
        for other in rectangles[index + 1:]:
            assert (x1 + padding <= other[0] - padding + 1e-9
                    or other[2] + padding <= x0 - padding + 1e-9
                    or y1 + padding <= other[1] - padding + 1e-9
                    or other[3] + padding <= y0 - padding + 1e-9)
    areas = [(rect[2] - rect[0]) * (rect[3] - rect[1]) for rect in rectangles]
    for index in range(1, len(areas)):
        assert math.isclose(areas[index] / areas[0], weights[index] / weights[0], rel_tol=1e-8)
    return sum(areas) / ((root[2] - root[0]) * (root[3] - root[1]))


def test_importance_packer_weight_ratio_strips_and_utilization():
    module = _load_primitives()
    assert _assert_packing(module, [4.0, 1.0], [1.0, 1.0]) > 0.55
    # With rotation forbidden, a 10:1 rectangle carrying 80% of the weight has
    # a theoretical utilization ceiling of 12.5% in a square.  The packer gets
    # close to that bound while preserving the strip's aspect ratio.
    assert _assert_packing(module, [4.0, 1.0], [10.0, 1.0]) > 0.12
    assert _assert_packing(module, [4.0, 1.0], [100.0, 1.0]) > 0.012


def test_importance_packer_multiple_mixed_orientation_and_padding():
    module = _load_primitives()
    utilization = _assert_packing(
        module, [5, 4, 3, 2, 1], [10, 8, 5, 0.2, 1], padding=1 / 1024)
    assert utilization > 0.05


def test_importance_packer_all_target_regions_and_determinism():
    module = _load_primitives()
    for region in ("FULL", "LEFT_HALF", "RIGHT_HALF"):
        root = module.target_rectangle(region)
        first = module.pack_importance_boxes([4, 2, 1], [6, 0.25, 1], root, 0.002)
        second = module.pack_importance_boxes([4, 2, 1], [6, 0.25, 1], root, 0.002)
        assert first == second
        _assert_packing(module, [4, 2, 1], [6, 0.25, 1], root, 0.002)


def test_shared_global_planner_area_ratio_regions_and_determinism():
    module = _load_primitives()
    class Vector:
        def __init__(self, x, y): self.x, self.y = x, y
    class Entry:
        def __init__(self, vector): self.vector = vector
    class Layer:
        def __init__(self, vectors): self.uv = [Entry(Vector(*v)) for v in vectors]
    def island(area, offset):
        item = module.IslandLayout((offset,), tuple(range(4)), area, 1, 1 / area)
        item.uv_layer = Layer(((0, 0), (1, 0), (1, 1), (0, 1)))
        item.source_bounds = (0, 0, 1, 1); item.uv_aspect = 1; item.uv_area = 1
        return item
    for region in ("FULL", "LEFT_HALF", "RIGHT_HALF"):
        islands = [island(4, 0), island(1, 1)]
        pending, report = module.plan_weighted_layout(
            islands, 0.0, "ALLOCATE_BY_IMPORTANCE", 2048, 4, region)
        areas = []
        root = module.target_rectangle(region)
        for _item, coords in pending:
            xs = [u for _, u, _ in coords]; ys = [v for _, _, v in coords]
            assert min(xs) >= root[0] and max(xs) <= root[2]
            assert min(ys) >= root[1] and max(ys) <= root[3]
            areas.append((max(xs)-min(xs)) * (max(ys)-min(ys)))
        assert math.isclose(areas[0] / areas[1], 4.0, rel_tol=1e-7)
        assert report.maximum_area_ratio_error < 1e-7
