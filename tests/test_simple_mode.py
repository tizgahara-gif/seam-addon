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


def test_simple_runner_has_object_mode_snapshot_transaction_order():
    function = next(node for node in _tree("simple_workflow.py").body
                    if isinstance(node, ast.FunctionDef)
                    and node.name == "_execute_stage")
    source = ast.unparse(function)
    context = source.index("operators._snapshot_context(context)")
    object_mode = source.index("operators._ensure_object_mode()")
    targets = source.index("resolve_simple_targets(context)")
    data = source.index("before = snapshot(targets.unique_objects)")
    operation = source.index("result = operation(targets.unique_objects)")
    assert context < object_mode < targets < data < operation
    assert "rollback also failed" in source
    assert "finally:\n        operators._restore_context" in source


def test_simple_policy_deduplicates_meshes_without_advanced_setting():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    resolver = ast.unparse(next(node for node in ast.parse(source).body
                                if isinstance(node, ast.FunctionDef)
                                and node.name == "resolve_simple_targets"))
    assert "obj.data.as_pointer()" in resolver
    assert "process_shared_mesh_once" not in source
    assert "settings.weighted_" not in source


def test_simple_ui_and_backend_share_readiness_resolver():
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    workflow = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    assert "targets = resolve_simple_targets(context)" in ui
    assert "targets = resolve_simple_targets(context)" in workflow
    assert "targets.all_uv_ready" in ui
    assert 'simple_symmetry_axis' in ui


def test_simple_discloses_mesh_targets_overlap_and_scale_warning():
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    workflow = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    assert 'text="Target: Selected Mesh Objects"' in ui
    assert 'text="Layout: Overlap"' in ui
    assert "unused space may remain in the current atlas" in ui
    assert "One unique mesh target will use Weighted Layout." in ui
    assert workflow.count("warn_scale=True") == 2
    assert "operators._warn_non_uniform_scale" in workflow


def test_symmetry_only_soft_skips_typed_not_found_error():
    function = next(node for node in _tree("simple_workflow.py").body
                    if isinstance(node, ast.FunctionDef) and node.name == "run_symmetry")
    source = ast.unparse(function)
    assert "except SymmetryNotFoundError as exc" in source
    assert "ProtectionError" not in source
    assert "ValueError" not in source
