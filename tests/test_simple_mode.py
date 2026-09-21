"""Static contracts for the Blender-independent part of Simple Mode."""

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / "auto_seam_uv_equalizer"


def _tree(name):
    return ast.parse((ROOT / name).read_text(encoding="utf-8"))


def test_simple_is_default_and_version_is_minor_bumped():
    properties = (ROOT / "properties.py").read_text(encoding="utf-8")
    init = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert 'default="SIMPLE"' in properties
    assert '"version": (0, 10, 0)' in init


def test_simple_pipeline_calls_shared_backends_in_order():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    positions = [source.index(f"{name}(", source.index("def execute")) for name in
                 ("run_chart_seam", "run_unwrap", "run_weighted_layout", "run_symmetry")]
    assert positions == sorted(positions)


def test_simple_operator_is_one_undo_step_and_has_no_algorithm_copy():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    assert 'bl_options = {"REGISTER", "UNDO"}' in source
    assert "analyze_chart_seams(" not in source
    assert "weighted_layout_object(" in source
    assert "shared_weighted_layout(" in source


def test_ui_branches_before_drawing_advanced_stages():
    source = (ROOT / "ui.py").read_text(encoding="utf-8")
    branch = source.index('if settings.ui_mode == "SIMPLE"')
    advanced = source.index("self._draw_seam(layout")
    assert branch < advanced
    assert 'operator("autoseamuv.simple_auto_uv", text="Auto UV Setup"' in source
