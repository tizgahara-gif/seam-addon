"""Operators for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy

from .seam_detection import clear_seams, mark_auto_seams, mark_advanced_seams, mark_longitudinal_seam_helper
from .symmetry import mirror_edge_map
from .uv_tools import ensure_uv_layer, unwrap_object, unwrap_object_pack
from .uv_validation import find_overlaps, triangles_from_object
from .ring_topology import TopologyError, analyze_ring_topology
from .ring_uv import assign_uv_loops, build_uv_coordinates, choose_seam


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


def _ring_face_indices(mesh):
    selected = [face.index for face in mesh.polygons if face.select]
    return selected if selected and len(selected) != len(mesh.polygons) else None


def _analyze_object_ring(obj, settings):
    grid = analyze_ring_topology(obj.data, _ring_face_indices(obj.data))
    seam = choose_seam(obj.data, grid, settings.ring_seam_mode)
    return grid, seam


class AUTOSEAMUV_OT_detect_ring_strip(bpy.types.Operator):
    """Validate selected topology without changing seams or UV data."""
    bl_idname = "autoseamuv.detect_ring_strip"
    bl_label = "Detect Ring / Strip"
    bl_options = {"REGISTER"}

    def execute(self, context):
        objects = _selected_visible_mesh_objects(context)
        if len(objects) != 1:
            self.report({"ERROR"}, "Ring / Strip: select exactly one visible mesh object.")
            return {"CANCELLED"}
        try:
            grid, seam = _analyze_object_ring(objects[0], _get_settings(context))
        except TopologyError as exc:
            self.report({"ERROR"}, f"Ring / Strip: Invalid - {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Ring / Strip: Valid; Rings {grid.ring_count}, Columns {grid.column_count}, Boundaries {grid.boundary_count}, Seam candidate {seam}")
        return {"FINISHED"}


class AUTOSEAMUV_OT_unwrap_ring_strip(bpy.types.Operator):
    """Generate loop UVs from a fully validated 3D quad grid."""
    bl_idname = "autoseamuv.unwrap_ring_strip"
    bl_label = "Unwrap Ring / Strip"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = _selected_visible_mesh_objects(context)
        if not selected:
            self.report({"ERROR"}, "Ring / Strip: no visible mesh object selected.")
            return {"CANCELLED"}
        settings = _get_settings(context)
        objects, skipped = _objects_for_processing(self, selected, settings.process_shared_mesh_once)
        active, original_selection, mode = _snapshot_context(context)
        completed = 0
        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    # Analysis, seam choice, and coordinate generation are pure;
                    # the UV layer is not even created until all validation ends.
                    grid, seam = _analyze_object_ring(obj, settings)
                    coordinates = build_uv_coordinates(obj.data, grid, seam, settings.ring_layout,
                                                       settings.ring_spacing, settings.ring_orientation,
                                                       settings.ring_normalize)
                    layer = obj.data.uv_layers.get(settings.uv_map_name)
                    if layer is None:
                        if not settings.create_uv_if_missing:
                            raise TopologyError(f"UV map '{settings.uv_map_name}' does not exist")
                        layer = obj.data.uv_layers.new(name=settings.uv_map_name)
                    assign_uv_loops(obj.data, layer, coordinates)
                    completed += 1
                    self.report({"INFO"}, f"{obj.name}: Rings {grid.ring_count}, Columns {grid.column_count}, Boundaries {grid.boundary_count}, Seam {seam}")
                except (TopologyError, ValueError) as exc:
                    self.report({"ERROR"}, f"{obj.name}: Invalid - {exc}")
        finally:
            _restore_context(context, active, original_selection, mode)
        self.report({"INFO"}, f"Ring / Strip: unwrapped {completed}, skipped shared {skipped}.")
        return {"FINISHED"} if completed else {"CANCELLED"}


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
                    total_marked += _auto_mark(obj, settings)
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
                    total_marked += _auto_mark(obj, settings)
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
                    if settings.atlas_uv_source == "ACTIVE":
                        has_uv = obj.data.uv_layers.active is not None
                    else:
                        has_uv = ensure_uv_layer(obj, settings.uv_map_name, settings.create_uv_if_missing)
                    if not has_uv:
                        failures += 1
                        detail = "active UV map" if settings.atlas_uv_source == "ACTIVE" else f"UV map '{settings.uv_map_name}'"
                        self.report({"WARNING"}, f"Atlas Pack Selected Objects: skipped {obj.name}; no {detail}.")
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
                bpy.ops.uv.pack_islands(
                    margin=atlas_margin,
                    margin_method="FRACTION",
                    rotate=settings.atlas_pack_rotate,
                )
            except TypeError:
                # Blender versions predating margin_method retain approximate behavior.
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

def _select_overlap_faces(objects, face_keys):
    for obj in objects:
        mesh = obj.data
        for poly in mesh.polygons:
            selected = (obj.name, poly.index) in face_keys
            poly.select = selected
        mesh.update()


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
        # Old .blend files may only contain overlap_epsilon.  Prefer the new
        # area property once it has been stored, otherwise migrate behavior in
        # memory without renaming/removing the legacy setting.
        area_epsilon = settings.get("overlap_area_epsilon", settings.overlap_epsilon)

        try:
            _ensure_object_mode()
            for obj in selected_objects:
                try:
                    if len(obj.data.polygons) == 0 or obj.data.uv_layers.active is None:
                        skipped += 1
                        continue
                    valid_objects.append(obj)
                    triangles.extend(triangles_from_object(obj, area_epsilon))
                except Exception as exc:
                    failed += 1
                    self.report({"ERROR"}, f"Check UV Overlap: failed to inspect {obj.name}: {exc}")

            overlap_faces = set()
            pair_count = 0
            seen_pairs = set()
            # Sweep on bbox min-X. This avoids the former unconditional T x T scan;
            # only triangles whose X ranges overlap become exact-test candidates.
            triangles.sort(key=lambda item: item["bbox"][0])
            for i, tri_a in enumerate(triangles):
                for tri_b in triangles[i + 1:]:
                    if tri_b["bbox"][0] >= tri_a["bbox"][2] - settings.overlap_epsilon:
                        break
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
            # Selection is deliberately the only visualization: material slots and
            # polygon material indices are never modified by validation.
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            f"Check UV Overlap: found {len(overlap_faces)} overlapping face(s) in {pair_count} pair(s), skipped {skipped}, failed {failed}.",
        )
        return {"FINISHED"} if valid_objects else {"CANCELLED"}


class AUTOSEAMUV_OT_clear_uv_overlap_highlight(bpy.types.Operator):
    """Clear the non-destructive UV overlap face selection."""

    bl_idname = "autoseamuv.clear_uv_overlap_highlight"
    bl_label = "Clear UV Overlap Highlight"
    bl_description = "Clear overlap face selection without changing materials"
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
                for poly in obj.data.polygons:
                    if poly.select:
                        cleared += 1
                    poly.select = False
                obj.data.update()
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
