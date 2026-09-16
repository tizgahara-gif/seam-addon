"""UV creation, unwrap, and equal-region packing helpers."""

from __future__ import annotations

import bpy

from .island_tools import straighten_circular_strip_islands_on_object
from .uv_pack import pack as blender_pack
from .uv_protection import (finished_face_indices, has_active_uv_protection, snapshot_finished,
                            selected_islands, validate_protection_consistency)


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

        validate_protection_consistency(obj)
        protected = snapshot_finished(obj.data)
        editable = set(range(len(obj.data.polygons))) - finished_face_indices(obj.data)
        if not editable:
            raise RuntimeError("all target UV islands are Finished")
        for face in obj.data.polygons:
            face.select = face.index in editable
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
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
        layer = obj.data.uv_layers.active
        for loop, uv in protected["uv"].items():
            layer.uv[loop].vector = uv
        obj.data.update()
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
    selected = {face.index for face in obj.data.polygons if face.select}
    if not selected:
        raise RuntimeError("no faces selected")
    if not ensure_uv_layer(obj, uv_map_name, create_if_missing):
        raise RuntimeError(f"UV map '{uv_map_name}' is unavailable")
    layer = obj.data.uv_layers.active
    layer_name = layer.name
    validate_protection_consistency(obj)
    selected = {face for island in selected_islands(obj, selected) for face in island}
    selected -= finished_face_indices(obj.data)
    if not selected:
        raise RuntimeError("all selected UV islands are Finished")
    for face in obj.data.polygons:
        face.select = face.index in selected
    untouched = {loop: layer.uv[loop].vector.copy()
                 for face in obj.data.polygons if face.index not in selected
                 for loop in face.loop_indices}
    before = {loop: datum.vector.copy() for loop, datum in enumerate(layer.uv)}
    bpy.ops.object.mode_set(mode="EDIT")
    try:
        result = bpy.ops.uv.unwrap(method=method, margin=margin)
        if "FINISHED" not in result:
            raise RuntimeError("Blender UV unwrap was cancelled")
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
        # Do not retain RNA members acquired before the mode transition.
        rollback_mesh = obj.data
        rollback_layer = rollback_mesh.uv_layers.get(layer_name)
        if rollback_layer is not None:
            for loop, uv in before.items():
                rollback_layer.uv[loop].vector = uv
            rollback_mesh.update()
        raise
    # A mode transition may invalidate RNA collection members.  Reacquire the
    # Mesh and UV layer before restoring untouched loops.
    mesh = obj.data
    layer = mesh.uv_layers.get(layer_name)
    if layer is None:
        raise RuntimeError(f"UV map '{layer_name}' became unavailable during unwrap")
    for loop, uv in untouched.items():
        layer.uv[loop].vector = uv
    mesh.update()
    bpy.ops.object.mode_set(mode="EDIT")



def pack_object(obj, settings) -> None:
    """Pack existing islands on the active UV map with Blender's pack operator."""
    if obj is None or obj.type != "MESH":
        return
    if has_active_uv_protection(obj.data):
        raise RuntimeError(
            "Pack Islands cannot preserve UV Protection. Use Weighted Island Layout "
            "or Pack Selected Into Free Space, or clear UV Protection first.")
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
