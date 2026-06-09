"""Operators for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy

from .seam_detection import clear_seams, mark_auto_seams, mark_longitudinal_seam_helper
from .island_tools import arrange_selected_uv_islands_to_grid
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
        if not (abs(scale.x - scale.y) < 1.0e-5 and abs(scale.y - scale.z) < 1.0e-5):
            names.append(obj.name)
    if names:
        operator.report(
            {"WARNING"},
            f"{REPORT_PREFIX}: non-uniform object scale detected; UV density may need manual review: {', '.join(names)}",
        )


def _get_settings(context):
    return context.scene.autoseamuv_settings


def _mesh_datablock_key(obj) -> int:
    return obj.data.as_pointer()


def _objects_for_processing(operator, objects: list[bpy.types.Object], process_shared_mesh_once: bool) -> tuple[list[bpy.types.Object], int]:
    if not process_shared_mesh_once:
        _warn_shared_meshes(operator, objects)
        return objects, 0

    seen_meshes: set[int] = set()
    process_objects: list[bpy.types.Object] = []
    skipped_names: list[str] = []

    for obj in objects:
        mesh_key = _mesh_datablock_key(obj)
        if mesh_key in seen_meshes:
            skipped_names.append(obj.name)
            continue
        seen_meshes.add(mesh_key)
        process_objects.append(obj)

    if skipped_names:
        operator.report(
            {"WARNING"},
            f"{REPORT_PREFIX}: shared mesh data skipped for {len(skipped_names)} object(s): {', '.join(skipped_names)}",
        )

    return process_objects, len(skipped_names)


class AUTOSEAMUV_OT_mark_only(bpy.types.Operator):
    """Automatically mark seams on selected mesh objects."""

    bl_idname = "autoseamuv.mark_only"
    bl_label = "Auto Mark Seams Only"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(self, selected_objects, settings.process_shared_mesh_once)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        total_marked = 0
        total_longitudinal = 0
        total_cleared = 0
        failures = 0

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
                    if settings.longitudinal_seam_helper:
                        total_longitudinal += mark_longitudinal_seam_helper(obj)
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, f"{REPORT_PREFIX}: failed to mark seams on {obj.name}: {exc}")
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: marked {total_marked} seam(s), longitudinal {total_longitudinal}, cleared {total_cleared}, processed {processed}, skipped shared {skipped_shared}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_unwrap_only(bpy.types.Operator):
    """Unwrap selected mesh objects using existing seams."""

    bl_idname = "autoseamuv.unwrap_only"
    bl_label = "Auto Unwrap Only"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(self, selected_objects, settings.process_shared_mesh_once)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        failures = 0

        _warn_non_uniform_scale(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.margin,
                        settings.average_islands,
                        settings.pack_islands,
                        settings.equal_region_pack,
                        settings.equal_region_margin,
                        settings.equal_region_layout,
                    )
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, str(exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: unwrapped {processed} object(s), marked 0 seam(s), skipped shared {skipped_shared}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_mark_and_unwrap(bpy.types.Operator):
    """Automatically mark seams and unwrap selected mesh objects."""

    bl_idname = "autoseamuv.mark_and_unwrap"
    bl_label = "Auto Seam + Unwrap"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(self, selected_objects, settings.process_shared_mesh_once)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        total_marked = 0
        total_longitudinal = 0
        total_cleared = 0
        failures = 0

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
                    if settings.longitudinal_seam_helper:
                        total_longitudinal += mark_longitudinal_seam_helper(obj)
                    unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.margin,
                        settings.average_islands,
                        settings.pack_islands,
                        settings.equal_region_pack,
                        settings.equal_region_margin,
                        settings.equal_region_layout,
                    )
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, str(exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: marked {total_marked} seam(s), longitudinal {total_longitudinal}, cleared {total_cleared}, unwrapped {processed}, skipped shared {skipped_shared}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_clear_seams(bpy.types.Operator):
    """Clear seams from selected mesh objects."""

    bl_idname = "autoseamuv.clear_seams"
    bl_label = "Clear Seams"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(self, selected_objects, settings.process_shared_mesh_once)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        total_cleared = 0
        failures = 0

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
            f"{REPORT_PREFIX}: cleared {total_cleared} seam(s), processed {processed}, skipped shared {skipped_shared}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_arrange_selected_uv_islands_to_grid(bpy.types.Operator):
    """Arrange selected UV islands into equal grid cells without unwrapping."""

    bl_idname = "autoseamuv.arrange_selected_uv_islands_to_grid"
    bl_label = "Arrange Selected UV Islands to Grid"
    bl_description = "Arrange selected UV islands into equal grid cells without unwrapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.view_layer.objects.active
        if obj is None or obj.type != "MESH":
            self.report({"WARNING"}, f"{REPORT_PREFIX}: active object must be a mesh.")
            return {"CANCELLED"}

        if context.mode != "EDIT_MESH" or obj.mode != "EDIT":
            self.report({"WARNING"}, f"{REPORT_PREFIX}: Arrange Selected UV Islands to Grid requires Edit Mode.")
            return {"CANCELLED"}

        if obj.data.uv_layers.active is None:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: {obj.name} has no active UV map.")
            return {"CANCELLED"}

        settings = _get_settings(context)

        try:
            arranged_count = arrange_selected_uv_islands_to_grid(
                obj,
                settings.arrange_selected_grid_margin,
                settings.arrange_selected_grid_layout,
                settings.duplicate_uv_before_arrange,
            )
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"{REPORT_PREFIX}: arranged {arranged_count} selected UV island(s) on {obj.name}.",
        )
        return {"FINISHED"}
