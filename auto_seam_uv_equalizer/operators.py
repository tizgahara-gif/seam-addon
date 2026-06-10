"""Operators for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy

from .seam_detection import clear_seams, mark_auto_seams, mark_longitudinal_seam_helper
from .uv_tools import ensure_uv_layer, unwrap_object, unwrap_object_pack


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
    bl_label = "Auto Unwrap Grid"
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
        total_straightened = 0

        _warn_non_uniform_scale(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    if len(obj.data.polygons) == 0:
                        self.report({"WARNING"}, f"{REPORT_PREFIX}: skipped {obj.name}; mesh has no faces.")
                        continue
                    total_straightened += unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.margin,
                        settings.average_islands,
                        False,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
                        True,
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
            f"{REPORT_PREFIX}: grid unwrapped {processed} object(s), marked 0 seam(s), straightened {total_straightened} circular strip island(s), skipped shared {skipped_shared}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_auto_unwrap_pack(bpy.types.Operator):
    """Unwrap selected mesh objects and pack UV islands efficiently."""

    bl_idname = "autoseamuv.auto_unwrap_pack"
    bl_label = "Auto Unwrap Pack"
    bl_description = "Unwrap selected mesh objects using existing settings, then pack UV islands efficiently into the 0-1 UV space"
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
        skipped_empty = 0
        failures = 0
        total_straightened = 0

        _warn_non_uniform_scale(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    if len(obj.data.polygons) == 0:
                        skipped_empty += 1
                        self.report({"WARNING"}, f"Auto Unwrap Pack: skipped {obj.name}; mesh has no faces.")
                        continue
                    total_straightened += unwrap_object_pack(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.margin,
                        settings.average_islands,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
                    )
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, str(exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"Auto Unwrap Pack: packed {processed} object(s), straightened {total_straightened} circular strip island(s), skipped empty {skipped_empty}, skipped shared {skipped_shared}, failed {failures}.",
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
        total_straightened = 0

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
                    total_straightened += unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.margin,
                        settings.average_islands,
                        settings.pack_islands,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
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
            f"{REPORT_PREFIX}: marked {total_marked} seam(s), longitudinal {total_longitudinal}, cleared {total_cleared}, unwrapped {processed}, straightened {total_straightened} circular strip island(s), skipped shared {skipped_shared}, failed {failures}.",
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_atlas_pack_selected_objects(bpy.types.Operator):
    """Pack active UV maps from selected mesh objects into one shared 0-1 atlas."""

    bl_idname = "autoseamuv.atlas_pack_selected_objects"
    bl_label = "Atlas Pack Selected Objects"
    bl_description = "Pack all UV islands from selected mesh objects into one 0-1 UV atlas without joining objects"
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
        skipped_empty = 0
        failures = 0
        valid_objects: list[bpy.types.Object] = []

        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    if len(obj.data.polygons) == 0:
                        skipped_empty += 1
                        self.report({"WARNING"}, f"Atlas Pack Selected Objects: skipped {obj.name}; mesh has no faces.")
                        continue
                    if not ensure_uv_layer(obj, settings.uv_map_name, settings.create_uv_if_missing):
                        failures += 1
                        self.report(
                            {"ERROR"},
                            f"Atlas Pack Selected Objects: {obj.name} has no UV map '{settings.uv_map_name}' and Create UV If Missing is disabled.",
                        )
                        continue
                    valid_objects.append(obj)
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, f"Atlas Pack Selected Objects: failed to prepare {obj.name}: {exc}")

            if not valid_objects:
                self.report(
                    {"WARNING"},
                    f"Atlas Pack Selected Objects: no valid mesh objects to pack, skipped empty {skipped_empty}, skipped shared {skipped_shared}, failed {failures}.",
                )
                return {"CANCELLED"}

            for obj in context.view_layer.objects:
                obj.select_set(False)
            for obj in valid_objects:
                obj.select_set(True)
            context.view_layer.objects.active = valid_objects[0]

            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_mode(type="FACE")
            bpy.ops.mesh.select_all(action="SELECT")

            if settings.atlas_average_island_scale:
                bpy.ops.uv.average_islands_scale()

            atlas_margin = settings.atlas_pixel_margin / settings.atlas_texture_size
            try:
                bpy.ops.uv.pack_islands(margin=atlas_margin, rotate=settings.atlas_pack_rotate)
            except TypeError:
                bpy.ops.uv.pack_islands(margin=atlas_margin)

            processed = len(valid_objects)
        except Exception as exc:
            failures += len(valid_objects) if valid_objects else 1
            self.report({"ERROR"}, f"Atlas Pack Selected Objects: failed to atlas pack selected objects: {exc}")
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"Atlas Pack Selected Objects: packed {processed} object(s), skipped empty {skipped_empty}, skipped shared {skipped_shared}, failed {failures}.",
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
