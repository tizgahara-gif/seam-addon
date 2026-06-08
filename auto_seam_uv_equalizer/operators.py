"""Operators for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy

from .seam_detection import clear_seams, mark_auto_seams
from .uv_tools import unwrap_object


REPORT_PREFIX = "Auto Seam UV"


def _selected_visible_mesh_objects(context) -> list[bpy.types.Object]:
    return [
        obj
        for obj in context.selected_objects
        if obj.type == "MESH" and obj.visible_get(view_layer=context.view_layer)
    ]


def _snapshot_context(context) -> tuple[bpy.types.Object | None, list[bpy.types.Object], str | None]:
    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    mode = active.mode if active is not None else None
    return active, selected, mode


def _restore_context(context, active, selected: list[bpy.types.Object], mode: str | None) -> None:
    try:
        if bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass

    for obj in context.view_layer.objects:
        try:
            obj.select_set(obj in selected)
        except Exception:
            pass

    if active is not None:
        try:
            context.view_layer.objects.active = active
        except Exception:
            pass

    if active is not None and mode and mode != "OBJECT":
        try:
            if active.select_get() and active.visible_get(view_layer=context.view_layer):
                bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass


def _ensure_object_mode() -> None:
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode="OBJECT")


def _warn_shared_meshes(operator, objects: list[bpy.types.Object]) -> None:
    shared = sorted({obj.data.name for obj in objects if obj.data.users > 1})
    if shared:
        operator.report(
            {"WARNING"},
            f"{REPORT_PREFIX}: shared mesh datablock(s) detected; seam and UV edits are shared: {', '.join(shared)}",
        )


def _warn_non_uniform_scale(operator, objects: list[bpy.types.Object]) -> None:
    names = []
    for obj in objects:
        scale = obj.scale
        if not (abs(scale.x - scale.y) < 1e-5 and abs(scale.y - scale.z) < 1e-5):
            names.append(obj.name)
    if names:
        operator.report(
            {"WARNING"},
            f"{REPORT_PREFIX}: non-uniform object scale detected; UV density may need manual review: {', '.join(names)}",
        )


def _get_settings(context):
    return context.scene.autoseamuv_settings


class AUTOSEAMUV_OT_mark_only(bpy.types.Operator):
    """Automatically mark seams on selected mesh objects."""

    bl_idname = "autoseamuv.mark_only"
    bl_label = "Auto Mark Seams Only"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _selected_visible_mesh_objects(context)
        if not objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        total_marked = 0
        total_cleared = 0
        failures = 0

        _warn_shared_meshes(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    if settings.clear_existing:
                        total_cleared += clear_seams(obj.data)
                    total_marked += mark_auto_seams(
                        obj,
                        settings.angle_threshold,
                        settings.material_boundary,
                        settings.boundary_edges,
                        settings.non_manifold_edges,
                    )
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, f"{REPORT_PREFIX}: failed to mark seams on {obj.name}: {exc}")
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: marked {total_marked} seam(s), cleared {total_cleared}, processed {processed}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_unwrap_only(bpy.types.Operator):
    """Unwrap selected mesh objects using existing seams."""

    bl_idname = "autoseamuv.unwrap_only"
    bl_label = "Auto Unwrap Only"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _selected_visible_mesh_objects(context)
        if not objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        failures = 0

        _warn_shared_meshes(self, objects)
        _warn_non_uniform_scale(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                if unwrap_object(
                    obj,
                    settings.uv_map_name,
                    settings.create_uv_if_missing,
                    settings.unwrap_method,
                    settings.margin,
                    settings.average_islands,
                    settings.pack_islands,
                ):
                    processed += 1
                else:
                    failures += 1
                    self.report({"ERROR"}, f"{REPORT_PREFIX}: failed to unwrap {obj.name}.")
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: unwrapped {processed} object(s), marked 0 seam(s), failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_mark_and_unwrap(bpy.types.Operator):
    """Automatically mark seams and unwrap selected mesh objects."""

    bl_idname = "autoseamuv.mark_and_unwrap"
    bl_label = "Auto Seam + Unwrap"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _selected_visible_mesh_objects(context)
        if not objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        total_marked = 0
        total_cleared = 0
        failures = 0

        _warn_shared_meshes(self, objects)
        _warn_non_uniform_scale(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    if settings.clear_existing:
                        total_cleared += clear_seams(obj.data)
                    total_marked += mark_auto_seams(
                        obj,
                        settings.angle_threshold,
                        settings.material_boundary,
                        settings.boundary_edges,
                        settings.non_manifold_edges,
                    )
                    if unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.margin,
                        settings.average_islands,
                        settings.pack_islands,
                    ):
                        processed += 1
                    else:
                        failures += 1
                        self.report({"ERROR"}, f"{REPORT_PREFIX}: failed to unwrap {obj.name}.")
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, f"{REPORT_PREFIX}: failed to process {obj.name}: {exc}")
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: marked {total_marked} seam(s), cleared {total_cleared}, unwrapped {processed}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_clear_seams(bpy.types.Operator):
    """Clear seams from selected mesh objects."""

    bl_idname = "autoseamuv.clear_seams"
    bl_label = "Clear Seams"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _selected_visible_mesh_objects(context)
        if not objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        active, selected, mode = _snapshot_context(context)
        processed = 0
        total_cleared = 0
        failures = 0

        _warn_shared_meshes(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    total_cleared += clear_seams(obj.data)
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, f"{REPORT_PREFIX}: failed to clear seams on {obj.name}: {exc}")
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: cleared {total_cleared} seam(s), processed {processed}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}
