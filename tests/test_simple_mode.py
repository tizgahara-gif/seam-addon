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
    assert '"version": (0, 11, 0)' in init


def test_simple_stages_call_shared_backends_independently():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    for class_name, backend in (
        ("AUTOSEAMUV_OT_simple_auto_seam", "run_chart_seam"),
        ("AUTOSEAMUV_OT_simple_auto_unwrap", "_run_unwrap_stage"),
        ("AUTOSEAMUV_OT_simple_auto_layout", "run_weighted_layout"),
        ("AUTOSEAMUV_OT_simple_auto_symmetry", "run_symmetry"),
    ):
        node = next(item for item in _tree("simple_workflow.py").body
                    if isinstance(item, ast.ClassDef) and item.name == class_name)
        called = {call.func.id for call in ast.walk(node)
                  if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
        assert backend in called
    assert "run_unwrap(obj, config)" in source


def test_simple_operators_are_undo_steps_and_have_no_algorithm_copy():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    assert source.count('bl_options = {"REGISTER", "UNDO"}') == 4
    assert "analyze_chart_seams(" not in source
    assert "weighted_layout_object(" in source
    assert "shared_weighted_layout(" in source


def test_ui_branches_before_drawing_advanced_stages():
    source = (ROOT / "ui.py").read_text(encoding="utf-8")
    branch = source.index('if settings.ui_mode == "SIMPLE"')
    advanced = source.index("self._draw_seam(layout")
    assert branch < advanced
    for identifier in ("simple_auto_seam", "simple_auto_unwrap",
                       "simple_auto_layout", "simple_auto_symmetry"):
        assert f'operator("autoseamuv.{identifier}"' in source
    assert "Auto UV Setup" not in source


def test_chart_adapter_is_typed_and_satisfies_shared_contract():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    assert "SimpleNamespace" not in source
    assert "class ChartSettings" in source
    assert "unwrap_method=config.unwrap_method" in source
    assert "CHART_ANALYSIS_SETTING_NAMES" in source


def test_each_stage_has_only_its_own_transaction_surface():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    seam = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                and node.name == "AUTOSEAMUV_OT_simple_auto_seam")
    unwrap = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                  and node.name == "AUTOSEAMUV_OT_simple_auto_unwrap")
    assert "_snapshot_seams" in ast.unparse(seam)
    assert "_snapshot_uvs" not in ast.unparse(seam)
    assert "_snapshot_uvs" in ast.unparse(unwrap)
    assert "run_chart_seam" not in ast.unparse(unwrap)


def test_mode_switch_and_simple_stages_do_not_assign_advanced_settings():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    assert "settings.unwrap_method =" not in source
    assert "settings.weighted_rotation_mode =" not in source
    assert "ui_mode =" not in source
