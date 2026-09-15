"""UV creation, unwrap, and equal-region packing helpers."""

from __future__ import annotations

import bpy

from .island_tools import straighten_circular_strip_islands_on_object
from .uv_pack import pack as blender_pack


def ensure_uv_layer(obj, uv_map_name: str, create_if_missing: bool) -> bool:
    """Activate the named UV map, optionally creating it when missing."""
    if obj is None or obj.type != "MESH":
        return 0

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


def unwrap_object(
    obj,
    uv_map_name: str,
    create_if_missing: bool,
    method: str,
    margin: float,
    average_islands: bool,
    straighten_circular_strip_islands: bool,
    circular_strip_min_faces: int,
    circular_strip_margin: float,
) -> int:
    """Unwrap one mesh object using current seams; never lay out or pack it."""
    if obj is None or obj.type != "MESH":
        return 0

    try:
        _switch_to_object_mode()
        _select_only_object(obj)

        if not ensure_uv_layer(obj, uv_map_name, create_if_missing):
            raise RuntimeError(f"UV map '{uv_map_name}' does not exist and Create UV If Missing is disabled.")

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.unwrap(method=method, margin=margin)

        straightened_count = 0
        if straighten_circular_strip_islands:
            bpy.ops.object.mode_set(mode="OBJECT")
            straightened_count = straighten_circular_strip_islands_on_object(
                obj,
                circular_strip_min_faces,
                circular_strip_margin,
            )
            bpy.ops.object.mode_set(mode="EDIT")

        if average_islands:
            bpy.ops.uv.average_islands_scale()

        bpy.ops.object.mode_set(mode="OBJECT")
        return straightened_count
    except Exception as exc:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        raise RuntimeError(f"Failed to unwrap {obj.name}: {exc}") from exc


def unwrap_selected_faces(obj, uv_map_name, create_if_missing, method, margin):
    """Unwrap selected Edit Mode faces and leave every other UV loop exact."""
    if obj is None or obj.type != "MESH" or obj.mode != "EDIT":
        raise RuntimeError("Edit Mode with selected faces is required")
    bpy.ops.object.mode_set(mode="OBJECT")
    if not ensure_uv_layer(obj, uv_map_name, create_if_missing):
        raise RuntimeError(f"UV map '{uv_map_name}' is unavailable")
    layer = obj.data.uv_layers.active
    selected = {face.index for face in obj.data.polygons if face.select}
    if not selected:
        bpy.ops.object.mode_set(mode="EDIT")
        raise RuntimeError("no faces selected")
    untouched = {loop: layer.uv[loop].vector.copy()
                 for face in obj.data.polygons if face.index not in selected
                 for loop in face.loop_indices}
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.unwrap(method=method, margin=margin)
    bpy.ops.object.mode_set(mode="OBJECT")
    for loop, uv in untouched.items():
        layer.uv[loop].vector = uv
    obj.data.update()
    bpy.ops.object.mode_set(mode="EDIT")



def pack_object(obj, settings) -> None:
    """Pack existing islands on the active UV map with Blender's pack operator."""
    if obj is None or obj.type != "MESH":
        return
    try:
        _switch_to_object_mode()
        _select_only_object(obj)
        if obj.data.uv_layers.active is None:
            raise RuntimeError("Pack Islands requires an active UV map.")
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        blender_pack(bpy, settings)
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as exc:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        raise RuntimeError(f"Failed to pack {obj.name}: {exc}") from exc
