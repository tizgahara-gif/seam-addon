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
                        settings.grid_cell_margin,
                        settings.equal_region_layout,
                        settings.grid_fit_to_cell,
                        settings.grid_cell_fill_ratio,
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

DEBUG_MATERIAL_NAME = "MAT_UV_OVERLAP_DEBUG"


def _polygon_area_2d(points):
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    return area * 0.5


def _inside_clip(point, edge_start, edge_end, orientation, epsilon):
    cross = (edge_end[0] - edge_start[0]) * (point[1] - edge_start[1]) - (edge_end[1] - edge_start[1]) * (point[0] - edge_start[0])
    return cross * orientation >= -epsilon


def _line_intersection_2d(a, b, c, d):
    abx = b[0] - a[0]
    aby = b[1] - a[1]
    cdx = d[0] - c[0]
    cdy = d[1] - c[1]
    denom = abx * cdy - aby * cdx
    if abs(denom) < 1.0e-12:
        return b
    t = ((c[0] - a[0]) * cdy - (c[1] - a[1]) * cdx) / denom
    return (a[0] + t * abx, a[1] + t * aby)


def _clipped_polygon(subject, clip, epsilon):
    output = list(subject)
    orientation = 1.0 if _polygon_area_2d(clip) >= 0.0 else -1.0
    for index, edge_start in enumerate(clip):
        edge_end = clip[(index + 1) % len(clip)]
        input_points = output
        output = []
        if not input_points:
            break
        previous = input_points[-1]
        previous_inside = _inside_clip(previous, edge_start, edge_end, orientation, epsilon)
        for current in input_points:
            current_inside = _inside_clip(current, edge_start, edge_end, orientation, epsilon)
            if current_inside:
                if not previous_inside:
                    output.append(_line_intersection_2d(previous, current, edge_start, edge_end))
                output.append(current)
            elif previous_inside:
                output.append(_line_intersection_2d(previous, current, edge_start, edge_end))
            previous = current
            previous_inside = current_inside
    return output


def _triangles_overlap_with_area(tri_a, tri_b, epsilon):
    clipped = _clipped_polygon(tri_a, tri_b, epsilon)
    return abs(_polygon_area_2d(clipped)) > epsilon


def _bbox_from_tri(tri):
    xs = [p[0] for p in tri]
    ys = [p[1] for p in tri]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_overlaps(a, b, epsilon):
    return not (a[2] <= b[0] + epsilon or b[2] <= a[0] + epsilon or a[3] <= b[1] + epsilon or b[3] <= a[1] + epsilon)


def _uv_face_triangles(obj, epsilon):
    mesh = obj.data
    uv_layer = mesh.uv_layers.active
    records = []
    for poly in mesh.polygons:
        if len(poly.loop_indices) < 3:
            continue
        uvs = [uv_layer.data[loop_index].uv.copy() for loop_index in poly.loop_indices]
        for idx in range(1, len(uvs) - 1):
            tri = ((uvs[0].x, uvs[0].y), (uvs[idx].x, uvs[idx].y), (uvs[idx + 1].x, uvs[idx + 1].y))
            if abs(_polygon_area_2d(tri)) > epsilon:
                records.append({"obj": obj, "face": poly.index, "tri": tri, "bbox": _bbox_from_tri(tri)})
    return records


def _ensure_overlap_debug_material():
    mat = bpy.data.materials.get(DEBUG_MATERIAL_NAME)
    if mat is None:
        mat = bpy.data.materials.new(DEBUG_MATERIAL_NAME)
    mat.diffuse_color = (1.0, 0.05, 0.02, 1.0)
    return mat


def _assign_debug_material(objects, face_keys):
    mat = _ensure_overlap_debug_material()
    for obj in objects:
        slot_index = obj.data.materials.find(DEBUG_MATERIAL_NAME)
        if slot_index < 0:
            obj.data.materials.append(mat)
            slot_index = len(obj.data.materials) - 1
        for poly in obj.data.polygons:
            if (obj.name, poly.index) in face_keys:
                poly.material_index = slot_index


def _select_overlap_faces(objects, face_keys):
    for obj in objects:
        mesh = obj.data
        uv_layer = mesh.uv_layers.active
        for poly in mesh.polygons:
            selected = (obj.name, poly.index) in face_keys
            poly.select = selected
            if uv_layer is not None:
                for loop_index in poly.loop_indices:
                    uv_layer.data[loop_index].select = selected


class AUTOSEAMUV_OT_check_uv_overlap(bpy.types.Operator):
    """Detect and highlight overlapping UV faces."""

    bl_idname = "autoseamuv.check_uv_overlap"
    bl_label = "Check UV Overlap"
    bl_description = "Detect and highlight overlapping UV faces"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}

        settings = _get_settings(context)
        active, selected, mode = _snapshot_context(context)
        valid_objects = []
        skipped = 0
        failed = 0
        triangles = []

        try:
            _ensure_object_mode()
            for obj in selected_objects:
                try:
                    if len(obj.data.polygons) == 0 or obj.data.uv_layers.active is None:
                        skipped += 1
                        continue
                    valid_objects.append(obj)
                    triangles.extend(_uv_face_triangles(obj, settings.overlap_epsilon))
                except Exception as exc:
                    failed += 1
                    self.report({"ERROR"}, f"Check UV Overlap: failed to inspect {obj.name}: {exc}")

            overlap_faces = set()
            pair_count = 0
            seen_pairs = set()
            for i, tri_a in enumerate(triangles):
                for tri_b in triangles[i + 1:]:
                    if tri_a["obj"] == tri_b["obj"] and tri_a["face"] == tri_b["face"]:
                        continue
                    if not settings.check_overlap_across_objects and tri_a["obj"] != tri_b["obj"]:
                        continue
                    if not _bbox_overlaps(tri_a["bbox"], tri_b["bbox"], settings.overlap_epsilon):
                        continue
                    if _triangles_overlap_with_area(tri_a["tri"], tri_b["tri"], settings.overlap_epsilon):
                        key_a = (tri_a["obj"].name, tri_a["face"])
                        key_b = (tri_b["obj"].name, tri_b["face"])
                        pair_key = tuple(sorted((key_a, key_b)))
                        if pair_key not in seen_pairs:
                            seen_pairs.add(pair_key)
                            pair_count += 1
                        overlap_faces.add(key_a)
                        overlap_faces.add(key_b)

            _select_overlap_faces(valid_objects, overlap_faces)
            if settings.assign_overlap_debug_material and overlap_faces:
                _assign_debug_material(valid_objects, overlap_faces)
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"Check UV Overlap: found {len(overlap_faces)} overlapping face(s) in {pair_count} pair(s), skipped {skipped}, failed {failed}.",
        )
        return {"FINISHED"} if valid_objects else {"CANCELLED"}


class AUTOSEAMUV_OT_clear_uv_overlap_highlight(bpy.types.Operator):
    """Clear UV overlap debug face and UV selection."""

    bl_idname = "autoseamuv.clear_uv_overlap_highlight"
    bl_label = "Clear UV Overlap Highlight"
    bl_description = "Clear overlap debug material selection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, f"{REPORT_PREFIX}: no visible mesh objects selected.")
            return {"CANCELLED"}
        active, selected, mode = _snapshot_context(context)
        cleared = 0
        try:
            _ensure_object_mode()
            for obj in selected_objects:
                uv_layer = obj.data.uv_layers.active
                debug_index = obj.data.materials.find(DEBUG_MATERIAL_NAME)
                for poly in obj.data.polygons:
                    if poly.select:
                        cleared += 1
                    poly.select = False
                    if debug_index >= 0 and poly.material_index == debug_index:
                        poly.material_index = 0
                    if uv_layer is not None:
                        for loop_index in poly.loop_indices:
                            uv_layer.data[loop_index].select = False
        finally:
            _restore_context(context, active, selected, mode)
        self.report({"INFO"}, f"Clear UV Overlap Highlight: cleared {cleared} selected face(s).")
        return {"FINISHED"}


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
