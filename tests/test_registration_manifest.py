"""Static registration-manifest invariants that do not require Blender."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "auto_seam_uv_equalizer"


def _class_names(path: Path, variable: str = "CLASSES") -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets)
    )
    names = []
    for item in assignment.value.elts:
        if isinstance(item, ast.Starred):
            module = item.value.value.id
            names.extend(_class_names(ROOT / f"{module}.py"))
        elif isinstance(item, ast.Name):
            names.append(item.id)
        else:
            names.append(item.attr)
    return names


def test_registration_manifest_has_unique_class_names():
    names = _class_names(ROOT / "__init__.py")
    assert len(names) == len(set(names))
    assert names.count("AUTOSEAMUV_PG_settings") == 1


def test_production_operator_surface_excludes_legacy_utilities():
    names = set(_class_names(ROOT / "__init__.py"))
    excluded = {
        "AUTOSEAMUV_OT_clear_seams",
        "AUTOSEAMUV_OT_seams_from_sharp", "AUTOSEAMUV_OT_sharp_from_seams",
        "AUTOSEAMUV_OT_select_seams", "AUTOSEAMUV_OT_select_open_edges",
        "AUTOSEAMUV_OT_create_seam_group", "AUTOSEAMUV_OT_update_seam_group",
        "AUTOSEAMUV_OT_apply_seam_group", "AUTOSEAMUV_OT_delete_seam_group",
        "AUTOSEAMUV_OT_get_texel_density", "AUTOSEAMUV_OT_set_texel_density",
    }
    assert names.isdisjoint(excluded)
    assert {
        "AUTOSEAMUV_OT_force_seam", "AUTOSEAMUV_OT_protect_seam",
        "AUTOSEAMUV_OT_clear_edge_tags", "AUTOSEAMUV_OT_mirror_seams",
        "AUTOSEAMUV_OT_validate_uv", "AUTOSEAMUV_OT_auto_unwrap_pack",
        "AUTOSEAMUV_OT_mark_and_unwrap",
    } <= names


def test_compatibility_operators_are_internal():
    tree = ast.parse((ROOT / "operators.py").read_text(encoding="utf-8"))
    classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
    for name in ("AUTOSEAMUV_OT_auto_unwrap_pack", "AUTOSEAMUV_OT_mark_and_unwrap"):
        options = next(
            node.value for node in classes[name].body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "bl_options"
                    for target in node.targets)
        )
        assert "INTERNAL" in ast.literal_eval(options)


def test_register_does_not_access_blender_datablocks_or_context_scene():
    """Registration runs while Blender may expose ``bpy.data`` as _RestrictData."""
    tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
    register = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "register"
    )

    def dotted_name(node):
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))

    accesses = {dotted_name(node) for node in ast.walk(register)
                if isinstance(node, ast.Attribute)}
    assert not any(name == "bpy.data" or name.startswith("bpy.data.")
                   for name in accesses)
    assert "bpy.context.scene" not in accesses
