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


def test_weighted_padding_resolver_modes_and_pixel_conversion():
    module = _load_primitives()
    settings = types.SimpleNamespace(
        weighted_padding_mode="PIXELS", weighted_padding_pixels=8,
        weighted_padding_uv=0.004, weighted_texture_resolution="2048")
    assert module.resolve_weighted_padding(settings) == 0.00390625
    settings.weighted_padding_mode = "RELATIVE"
    assert module.resolve_weighted_padding(settings) == 0.004
    settings.weighted_texture_resolution = "8192"
    assert module.resolve_weighted_padding(settings) == 0.004


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


def test_rotation_off_is_identical_and_square_tie_prefers_zero_degrees():
    module = _load_primitives()
    boxes = [(0.7, 0.2), (0.2, 0.7), (0.1, 0.1)]
    legacy = module._maxrects_pack(boxes, (0, 0, 1, 1), 0.01)
    explicit_off = module._maxrects_pack(boxes, (0, 0, 1, 1), 0.01, False)
    assert legacy == explicit_off
    square = module._maxrects_pack([(0.4, 0.4)], (0, 0, 1, 1), 0, True)
    assert square[0].rotated_90 is False


def test_rotation_rescues_fit_and_swaps_padded_body_bbox():
    module = _load_primitives()
    assert module._maxrects_pack([(0.7, 0.2)], (0, 0, 0.3, 0.8), 0.01, False) is None
    packed = module._maxrects_pack([(0.7, 0.2)], (0, 0, 0.3, 0.8), 0.01, True)[0]
    assert packed.rotated_90 is True
    assert math.isclose(packed.width, 0.2)
    assert math.isclose(packed.height, 0.7)
    assert packed.x >= 0.01 and packed.y >= 0.01
    assert packed.x + packed.width <= 0.3 - 0.01 + 1e-12
    assert packed.y + packed.height <= 0.8 - 0.01 + 1e-12


def test_rotation_packer_is_deterministic_in_every_target_region():
    module = _load_primitives()
    for region in ("FULL", "LEFT_HALF", "RIGHT_HALF"):
        root = module.target_rectangle(region)
        args = ([5, 4, 3, 2], [8, 0.15, 5, 0.25], root, 0.002, True)
        first = module.pack_importance_boxes(*args)
        assert first == module.pack_importance_boxes(*args)
        for packed in first[0]:
            assert root[0] <= packed.x
            assert packed.x + packed.width <= root[2] + 1e-9
            assert root[1] <= packed.y
            assert packed.y + packed.height <= root[3] + 1e-9


def test_planner_rotates_real_uv_shape_without_area_or_edge_distortion():
    module = _load_primitives()
    class Vector:
        def __init__(self, x, y): self.x, self.y = x, y
    class Entry:
        def __init__(self, vector): self.vector = Vector(*vector)
    class Layer:
        def __init__(self, width, height):
            self.uv = [Entry(v) for v in ((0, 0), (width, 0),
                                           (width, height), (0, height))]
    aspects = (8, .15, 5, .25)
    islands = []
    for index, aspect in enumerate(aspects):
        width, height = math.sqrt(aspect), 1 / math.sqrt(aspect)
        item = module.IslandLayout((index,), tuple(range(4)), 1.0, 1, 1.0)
        item.uv_layer = Layer(width, height)
        item.source_bounds = (0, 0, width, height)
        item.uv_aspect = aspect; item.uv_area = width * height
        islands.append(item)
    pending, report = module.plan_weighted_layout(
        islands, 0, "ALLOCATE_BY_IMPORTANCE", 0, "FULL", True)
    assert report.rotated_island_count > 0
    transformed_areas = []
    for item, coordinates in pending:
        coords = [(u, v) for _, u, v in coordinates]
        edges = [math.dist(coords[i], coords[(i + 1) % 4]) for i in range(4)]
        assert math.isclose(edges[0] / edges[1], item.uv_aspect, rel_tol=1e-9)
        bbox_aspect = ((max(u for u, _ in coords) - min(u for u, _ in coords)) /
                       (max(v for _, v in coords) - min(v for _, v in coords)))
        expected_aspect = 1 / item.uv_aspect if item.packed_rect.rotated_90 else item.uv_aspect
        assert math.isclose(bbox_aspect, expected_aspect, rel_tol=1e-9)
        # Shoelace area equals the plan's uniform-scale area prediction even
        # for islands whose actual UV loops received the 90° CCW transform.
        area = abs(sum(coords[i][0] * coords[(i + 1) % 4][1]
                       - coords[(i + 1) % 4][0] * coords[i][1]
                       for i in range(4))) * .5
        transformed_areas.append(area)
    assert all(math.isclose(area, transformed_areas[0], rel_tol=1e-9)
               for area in transformed_areas)
    assert report.maximum_area_ratio_error < 1e-9


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
            islands, 0.0, "ALLOCATE_BY_IMPORTANCE", 4 / 2048, region)
        areas = []
        root = module.target_rectangle(region)
        for _item, coords in pending:
            xs = [u for _, u, _ in coords]; ys = [v for _, _, v in coords]
            assert min(xs) >= root[0] and max(xs) <= root[2]
            assert min(ys) >= root[1] and max(ys) <= root[3]
            areas.append((max(xs)-min(xs)) * (max(ys)-min(ys)))
        assert math.isclose(areas[0] / areas[1], 4.0, rel_tol=1e-7)
        assert report.maximum_area_ratio_error < 1e-7


def test_planner_is_resolution_independent_and_equivalent_padding_matches():
    module = _load_primitives()

    class Vector:
        def __init__(self, x, y): self.x, self.y = x, y
    class Entry:
        def __init__(self, vector): self.vector = Vector(*vector)
    class Layer:
        def __init__(self): self.uv = [Entry(v) for v in ((0, 0), (1, 0), (1, 1), (0, 1))]
    def islands():
        result = []
        for offset, area in enumerate((4.0, 1.0)):
            item = module.IslandLayout((offset,), tuple(range(4)), area, 1, 1 / area)
            item.uv_layer = Layer(); item.source_bounds = (0, 0, 1, 1)
            item.uv_aspect = 1.0; item.uv_area = 1.0
            result.append(item)
        return result
    def plan(padding):
        pending, report = module.plan_weighted_layout(
            islands(), 0.25, "ALLOCATE_BY_IMPORTANCE", padding)
        return [[tuple(coordinate) for coordinate in coordinates]
                for _item, coordinates in pending], report

    relative_512 = types.SimpleNamespace(
        weighted_padding_mode="RELATIVE", weighted_padding_uv=0.004,
        weighted_padding_pixels=8, weighted_texture_resolution="512")
    relative_8192 = types.SimpleNamespace(**vars(relative_512))
    relative_8192.weighted_texture_resolution = "8192"
    assert plan(module.resolve_weighted_padding(relative_512)) == plan(
        module.resolve_weighted_padding(relative_8192))

    pixels = types.SimpleNamespace(
        weighted_padding_mode="PIXELS", weighted_padding_uv=0.0,
        weighted_padding_pixels=8, weighted_texture_resolution="2048")
    relative = types.SimpleNamespace(
        weighted_padding_mode="RELATIVE", weighted_padding_uv=0.00390625,
        weighted_padding_pixels=0, weighted_texture_resolution="512")
    assert plan(module.resolve_weighted_padding(pixels)) == plan(
        module.resolve_weighted_padding(relative))
