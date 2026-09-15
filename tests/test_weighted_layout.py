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
