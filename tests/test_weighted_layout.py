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


def test_weighted_rectangles_are_finite_positive_and_non_overlapping():
    module = _load_primitives()
    rectangles = module.weighted_rectangles([100.0, 1.0, 1e-300, 4.0])
    for index, rect in enumerate(rectangles):
        assert all(math.isfinite(value) for value in rect)
        assert rect[2] > rect[0] and rect[3] > rect[1]
        for other in rectangles[index + 1:]:
            overlap_width = min(rect[2], other[2]) - max(rect[0], other[0])
            overlap_height = min(rect[3], other[3]) - max(rect[1], other[1])
            assert overlap_width <= 1e-12 or overlap_height <= 1e-12


def test_aspect_aware_strip_allocation_and_weight_area_correction():
    module = _load_primitives()
    rectangles = module.weighted_rectangles([4.0, 1.0], aspects=[10.0, 1.0])
    strip = rectangles[0]
    strip_aspect = (strip[2] - strip[0]) / (strip[3] - strip[1])
    assert strip_aspect > 1.0

    # Unit-height source bboxes: the strip is 10x1 and the other island 1x1.
    fits = [min((strip[2] - strip[0]) / 10.0, strip[3] - strip[1]),
            min(rectangles[1][2] - rectangles[1][0], rectangles[1][3] - rectangles[1][1])]
    scales = module.importance_scales([10.0, 1.0], [4.0, 1.0], fits)
    final_areas = [10.0 * scales[0] ** 2, scales[1] ** 2]
    assert math.isclose(final_areas[0] / final_areas[1], 4.0, rel_tol=1e-12)
    assert all(scale <= fit + 1e-12 for scale, fit in zip(scales, fits))


def test_extreme_strip_has_valid_preferred_rectangle_and_larger_area():
    module = _load_primitives()
    rectangles = module.weighted_rectangles([4.0, 1.0], aspects=[100.0, 1.0])
    assert all(rect[2] > rect[0] and rect[3] > rect[1]
               and all(math.isfinite(value) for value in rect) for rect in rectangles)
    strip = rectangles[0]
    assert (strip[2] - strip[0]) > (strip[3] - strip[1])
    fits = [min((strip[2] - strip[0]) / 100.0, strip[3] - strip[1]),
            min(rectangles[1][2] - rectangles[1][0], rectangles[1][3] - rectangles[1][1])]
    scales = module.importance_scales([100.0, 1.0], [4.0, 1.0], fits)
    assert 100.0 * scales[0] ** 2 > scales[1] ** 2


def test_target_region_rectangles_stay_inside_each_root():
    module = _load_primitives()
    for region, expected in (("FULL", (0.0, 1.0)),
                             ("LEFT_HALF", (0.0, 0.5)),
                             ("RIGHT_HALF", (0.5, 1.0))):
        root = module.target_rectangle(region)
        for x0, y0, x1, y1 in module.weighted_rectangles([4, 2, 1], root, [10, 1, 0.2]):
            assert expected[0] <= x0 < x1 <= expected[1]
            assert 0.0 <= y0 < y1 <= 1.0


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
    # close to that bound rather than suffering the partition allocator's waste.
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
