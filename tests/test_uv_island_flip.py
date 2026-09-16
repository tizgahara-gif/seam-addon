import importlib.util
import math
import sys
import types
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "auto_seam_uv_equalizer" / "uv_island_flip.py"


def _load_module():
    package = sys.modules.setdefault(
        "auto_seam_uv_equalizer", types.ModuleType("auto_seam_uv_equalizer"))
    package.__path__ = [str(MODULE.parent)]
    island = types.ModuleType("auto_seam_uv_equalizer.island_tools")
    island.find_uv_islands = lambda _obj: []
    mesh = types.ModuleType("auto_seam_uv_equalizer.mesh_utils")
    mesh.build_mesh_topology = lambda _mesh: ({}, {}, {}, {})
    sys.modules[island.__name__] = island
    sys.modules[mesh.__name__] = mesh
    spec = importlib.util.spec_from_file_location(
        "auto_seam_uv_equalizer.uv_island_flip", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_single_island_flips_u_and_preserves_v_and_bounds():
    module = _load_module()
    before = ((0, .1, .2), (1, .3, .2), (2, .3, .6), (3, .1, .6))
    plan = module.plan_horizontal_uv_flip([module.UVFlipIsland(before)])
    expected = {0: (.3, .2), 1: (.1, .2), 2: (.1, .6), 3: (.3, .6)}
    assert plan.keys() == expected.keys()
    for index in plan:
        assert plan[index] == pytest.approx(expected[index])
    assert (min(u for u, _v in plan.values()),
            max(u for u, _v in plan.values())) == pytest.approx((.1, .3))


def test_multiple_islands_have_independent_pivots_including_udim_uvs():
    module = _load_module()
    islands = [
        module.UVFlipIsland(((0, .1, 0.), (1, .3, 1.))),
        module.UVFlipIsland(((2, 1.2, 2.), (3, 1.6, 3.))),
    ]
    plan = module.plan_horizontal_uv_flip(islands)
    expected = {0: (.3, 0.), 1: (.1, 1.), 2: (1.6, 2.), 3: (1.2, 3.)}
    assert plan.keys() == expected.keys()
    for index in plan:
        assert plan[index] == pytest.approx(expected[index])


def test_zero_width_island_is_a_noop_and_non_finite_uv_is_rejected():
    module = _load_module()
    island = module.UVFlipIsland(((0, .5, .2), (1, .5, .8)))
    assert module.plan_horizontal_uv_flip([island]) == {0: (.5, .2), 1: (.5, .8)}
    invalid = module.UVFlipIsland(((2, math.inf, 0.),))
    try:
        module.plan_horizontal_uv_flip([island, invalid])
    except ValueError as exc:
        assert "non-finite" in str(exc)
    else:
        raise AssertionError("non-finite UV must fail before commit")


def test_no_islands_is_rejected():
    module = _load_module()
    try:
        module.plan_horizontal_uv_flip([])
    except ValueError as exc:
        assert str(exc) == "No selected UV islands found."
    else:
        raise AssertionError("empty selection must be rejected")
