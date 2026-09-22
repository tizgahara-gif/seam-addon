"""Source-level guards for Blender mode transactions.

The behavior is also exercised against real Blender RNA in
``blender_tests/test_integration.py``.  These fast tests make accidental
reintroduction of the unsafe call ordering visible in normal CI.
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "auto_seam_uv_equalizer"


def _method(path, class_name, method_name="execute"):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    return next(node for node in cls.body
                if isinstance(node, ast.FunctionDef) and node.name == method_name)


def _function(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name)


def _calls(node):
    result = []
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        function = item.func
        result.append(function.id if isinstance(function, ast.Name)
                      else function.attr if isinstance(function, ast.Attribute) else "")
    return result


def test_incremental_operator_snapshots_faces_and_uses_object_mode_transaction():
    method = _method("operators.py", "AUTOSEAMUV_OT_pack_selected_into_free_space")
    source = ast.unparse(method)
    assert "frozenset" in source
    assert "selected_face_indices=selected_faces" in source
    assert "obj.update_from_editmode" not in source
    assert source.index("_snapshot_context(context)") < source.index("_ensure_object_mode()")
    assert source.index("_ensure_object_mode()") < source.index("incremental_pack_object(")
    assert "finally:\n        _restore_context(context, active, selected, mode)" in source


def test_incremental_backend_orders_barrier_snapshot_commit_and_rollback():
    function = _function("weighted_layout.py", "incremental_pack_object")
    source = ast.unparse(function)
    assert source.index("collect_weighted_islands") < source.index("validate_protection_consistency")
    assert source.index("plan_weighted_layout") < source.index("assert_plan_does_not_modify_finished")
    assert source.index("assert_plan_does_not_modify_finished") < source.index("before =")
    assert source.index("before =") < source.index("apply_weighted_plan(pending)")
    assert "for loop, uv in before.items()" in source


def test_auto_unwrap_pack_preflight_precedes_context_snapshot_and_unwrap():
    method = _method("operators.py", "AUTOSEAMUV_OT_auto_unwrap_pack")
    source = ast.unparse(method)
    preflight = source.index("has_active_uv_protection")
    assert preflight < source.index("_snapshot_context")
    assert preflight < source.index("unwrap_object")


def test_mark_and_unwrap_pack_preflight_precedes_seam_mutation():
    method = _method("operators.py", "AUTOSEAMUV_OT_mark_and_unwrap")
    source = ast.unparse(method)
    preflight = source.index("settings.pack_islands and any")
    assert preflight < source.index("_snapshot_context")
    assert preflight < source.index("clear_seams")
    assert preflight < source.index("_auto_mark")


def test_unwrap_selected_faces_reacquires_active_layer_after_mode_switch():
    function = _function("uv_tools.py", "unwrap_selected_faces")
    source = ast.unparse(function)
    last_object_mode = source.rindex("bpy.ops.object.mode_set(mode='OBJECT')")
    reacquire_mesh = source.index("mesh = obj.data", last_object_mode)
    reacquire_layer = source.index("layer = mesh.uv_layers.get(active_uv_name)", reacquire_mesh)
    restore_write = source.index("layer.uv[loop].vector = uv", reacquire_layer)
    assert last_object_mode < reacquire_mesh < reacquire_layer < restore_write
    assert "active_uv_name = active_layer.name" in source
    assert "ensure_uv_layer" not in source
    assert [arg.arg for arg in function.args.args] == ["obj", "method", "margin_method", "margin"]
    assert "before =" in source
    assert "for loop, uv in before.items()" in source
    assert "Blender UV unwrap was cancelled" in source


def test_unwrap_selected_operator_always_restores_component_context():
    method = _method("operators.py", "AUTOSEAMUV_OT_unwrap_selected_faces")
    source = ast.unparse(method)
    snapshot = source.index("_snapshot_context(context)")
    unwrap = source.index("unwrap_selected_faces(")
    restore = source.index(
        "_restore_context(context, active, selected_objects, original_mode)")
    assert snapshot < unwrap < restore
    assert "finally:" in source


def test_incremental_operator_has_active_object_preflight_before_transaction():
    method = _method("operators.py", "AUTOSEAMUV_OT_pack_selected_into_free_space")
    source = ast.unparse(method)
    snapshot = source.index("_snapshot_context(context)")
    assert source.index("context.mode != 'EDIT_MESH'") < snapshot
    assert source.index("obj.data.uv_layers.active is None") < snapshot
    assert source.index("if not selected_faces") < snapshot


def test_simple_uv_transaction_uses_blender_51_layer_collections_and_flags():
    snapshot = ast.unparse(_function("simple_workflow.py", "_snapshot_uvs"))
    rollback = ast.unparse(_function("simple_workflow.py", "_rollback_uvs"))

    # MeshUVLoopLayer.pin/vertex_selection/edge_selection already are
    # bpy_prop_collection instances.  Accessing a second `.data` level is the
    # Blender 5.1 regression this guard exists to prevent.
    assert "collection.data" not in snapshot
    assert "collection.data" not in rollback
    assert "for item in collection" in snapshot
    assert "zip(collection, values)" in rollback

    # Render and clone roles are layer booleans in Blender 5.1; do not invent
    # collection-level active_* accessors or indices.
    assert "bool(layer.active)" in snapshot
    assert "bool(layer.active_render)" in snapshot
    assert "bool(layer.active_clone)" in snapshot
    assert "active_render_index" not in rollback
    assert "active_clone_index" not in rollback


def test_simple_uv_snapshot_is_value_only_and_rollback_reacquires_by_name():
    source = (ROOT / "simple_workflow.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    snapshot_type = next(node for node in tree.body
                         if isinstance(node, ast.ClassDef)
                         and node.name == "UVLayerSnapshot")
    fields = {node.target.id for node in snapshot_type.body
              if isinstance(node, ast.AnnAssign)
              and isinstance(node.target, ast.Name)}
    assert {"index", "name", "coordinates", "active", "active_render",
            "active_clone", "pins", "vertex_selection", "edge_selection"} == fields
    assert "layer" not in fields
    assert "pointer" not in fields
    assert ".as_pointer()" not in ast.unparse(
        _function("simple_workflow.py", "_rollback_uvs"))
    assert "mesh.uv_layers.get(item.name)" in ast.unparse(
        _function("simple_workflow.py", "_rollback_uvs"))
