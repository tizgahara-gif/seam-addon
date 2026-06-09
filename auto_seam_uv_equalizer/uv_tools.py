"""UV creation and unwrap helpers for Auto Seam UV Equalizer."""

from __future__ import annotations

from collections.abc import Callable

import bpy

from .island_tools import apply_material_uv_scale_rules, parse_material_scale_rules

WarningCallback = Callable[[str], None]


def ensure_uv_layer(obj, uv_map_name: str, create_if_missing: bool) -> bool:
    """Activate the named UV map, optionally creating it when missing."""
    if obj is None or obj.type != "MESH":
        return False

    mesh = obj.data
    uv_layers = mesh.uv_layers
    target_name = uv_map_name.strip() or "UV_Auto"

    if target_name in uv_layers:
        uv_layers.active = uv_layers[target_name]
        return True

    if not create_if_missing:
        return False

    uv_layers.new(name=target_name)
    uv_layers.active = uv_layers[target_name]
    return True


def _switch_to_object_mode() -> None:
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode="OBJECT")


def _select_only_object(obj) -> None:
    for selected in list(bpy.context.selected_objects):
        selected.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def _report_rule_warnings(rule_warnings: list[str], warning_callback: WarningCallback | None) -> None:
    if warning_callback is None:
        return

    for warning in rule_warnings:
        warning_callback(warning)


def _apply_material_scaling_if_needed(obj, material_scale_rules: str, warning_callback: WarningCallback | None) -> int:
    rules, rule_warnings = parse_material_scale_rules(material_scale_rules)
    _report_rule_warnings(rule_warnings, warning_callback)

    if not rules:
        return 0

    _switch_to_object_mode()
    return apply_material_uv_scale_rules(obj, rules)


def unwrap_object(
    obj,
    uv_map_name: str,
    create_if_missing: bool,
    method: str,
    margin: float,
    average_islands: bool,
    pack_islands: bool,
    material_scale_rules: str = "",
    warning_callback: WarningCallback | None = None,
) -> bool:
    """Unwrap one mesh object using the currently marked seams."""
    if obj is None or obj.type != "MESH":
        return False

    try:
        _switch_to_object_mode()
        _select_only_object(obj)

        if not ensure_uv_layer(obj, uv_map_name, create_if_missing):
            raise RuntimeError(f"UV map '{uv_map_name}' does not exist and Create UV If Missing is disabled.")

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.unwrap(method=method, margin=margin)

        if average_islands:
            bpy.ops.uv.average_islands_scale()

        _apply_material_scaling_if_needed(obj, material_scale_rules, warning_callback)

        if pack_islands:
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.uv.pack_islands(margin=margin)

        bpy.ops.object.mode_set(mode="OBJECT")
        return True
    except Exception as exc:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        raise RuntimeError(f"Failed to unwrap {obj.name}: {exc}") from exc
