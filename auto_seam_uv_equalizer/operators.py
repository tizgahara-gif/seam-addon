"""Operators for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy
import bmesh
from bpy.props import BoolProperty

from .seam_detection import (
    clear_seams,
    analyze_chart_seams,
    apply_chart_seams,
    analysis_signature,
    mark_auto_seams,
    mark_longitudinal_seam_helper,
    mark_selected_region_boundary_seams,
)
from .uv_tools import ensure_uv_layer, pack_object, unwrap_object, unwrap_selected_faces
from .weighted_layout import weighted_layout_object
from .uv_validation import find_overlaps, triangles_from_object
from .ring_topology import TopologyError, analyze_ring_topology
from .ring_uv import assign_uv_loops, build_uv_coordinates, choose_seam
from .translations import iface_
from .chart_seam import (PRESETS, cached_uv_quality_evaluator,
                         uv_chart_quality_from_snapshot)


REPORT_PREFIX = "Auto Seam UV"
_EDIT_SELECTION_SNAPSHOTS = {}
_CHART_ANALYSIS_CACHE = {}


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
    _EDIT_SELECTION_SNAPSHOTS.clear()
    if active is not None and mode == "EDIT" and active.type == "MESH":
        # Deduplicate by Mesh because linked objects expose the same edit
        # BMesh, and therefore the same component-selection state.
        edit_objects = getattr(context, "objects_in_mode", ()) or (active,)
        select_mode = tuple(context.tool_settings.mesh_select_mode)
        for obj in edit_objects:
            if obj.type != "MESH":
                continue
            mesh_key = obj.data.as_pointer()
            if mesh_key in _EDIT_SELECTION_SNAPSHOTS:
                continue
            bm = bmesh.from_edit_mesh(obj.data)
            bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
            _EDIT_SELECTION_SNAPSHOTS[mesh_key] = (
                obj.data,
                {item.index for item in bm.verts if item.select},
                {item.index for item in bm.edges if item.select},
                {item.index for item in bm.faces if item.select},
                select_mode,
            )
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
    if active is not None and mode == "EDIT" and active.type == "MESH":
        snapshots = list(_EDIT_SELECTION_SNAPSHOTS.values())
        _EDIT_SELECTION_SNAPSHOTS.clear()
        for mesh, vertices, edges, faces, select_mode in snapshots:
            context.tool_settings.mesh_select_mode = select_mode
            bm = bmesh.from_edit_mesh(mesh)
            bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
            for item in bm.verts: item.select = item.index in vertices
            for item in bm.edges: item.select = item.index in edges
            for item in bm.faces: item.select = item.index in faces
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


def _restore_validation_context(context, active, selected, mode):
    """Restore object/mode context while intentionally retaining face results."""
    select_modes = [snapshot[4] for snapshot in _EDIT_SELECTION_SNAPSHOTS.values()]
    _EDIT_SELECTION_SNAPSHOTS.clear()
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
        context.view_layer.objects.active = active
    if active is not None and mode and mode != "OBJECT" and active.select_get():
        try:
            bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass
    if select_modes:
        context.tool_settings.mesh_select_mode = select_modes[0]


def _ensure_object_mode() -> None:
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode="OBJECT")


def _warn_shared_meshes(operator, objects: list[bpy.types.Object]) -> None:
    shared = sorted({obj.data.name for obj in objects if obj.data.users > 1})
    if shared:
        operator.report(
            {"WARNING"},
            iface_("Auto Seam UV: shared mesh datablock(s) detected; seam and UV edits are shared: %s", ", ".join(shared)),
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
            iface_("Auto Seam UV: non-uniform object scale detected; UV density may need manual review: %s", ", ".join(names)),
        )


def _get_settings(context):
    return context.scene.autoseamuv_settings


def _auto_mark(obj, settings) -> int:
    """Dispatch to the selected seam engine with its complete settings."""
    if settings.seam_mode == "ADVANCED":
        return apply_chart_seams(obj, _analyze_with_temporary_unwrap(obj, settings))
    return mark_auto_seams(
        obj,
        settings.angle_threshold,
        settings.material_boundary,
        settings.boundary_edges,
        settings.non_manifold_edges,
    )


def _mesh_datablock_key(obj) -> int:
    return obj.data.as_pointer()


def _analyze_with_temporary_unwrap(obj, settings):
    """Evaluate plans on an isolated mesh copy; the user's UV maps stay untouched."""
    temp_mesh = obj.data.copy()
    temp_obj = obj.copy()
    temp_obj.data = temp_mesh
    temp_obj.name = "__AutoSeamUV_ChartAnalysis__"
    context = bpy.context
    context.collection.objects.link(temp_obj)
    def unwrap_snapshot(cuts):
        for edge in temp_mesh.edges:
            edge.use_seam = edge.index in cuts
        method = PRESETS.get(settings.seam_preset, PRESETS["HARD_SURFACE"]).method
        unwrap_object(temp_obj, "__AutoSeamUV_Temporary__", True, method, 0.0,
                      False, False, 3, 0.0)
        return tuple(item.vector.copy() for item in temp_mesh.uv_layers.active.uv)

    evaluate = cached_uv_quality_evaluator(
        unwrap_snapshot,
        lambda snapshot, chart: uv_chart_quality_from_snapshot(
            temp_mesh, snapshot, chart),
    )

    try:
        return analyze_chart_seams(obj, settings, evaluate)
    finally:
        if temp_obj.name in context.view_layer.objects:
            bpy.data.objects.remove(temp_obj, do_unlink=True)
        bpy.data.meshes.remove(temp_mesh)


class AUTOSEAMUV_OT_analyze_seams(bpy.types.Operator):
    """Analyze provisional charts without changing seams, UVs, or selection."""

    bl_idname = "autoseamuv.analyze_seams"
    bl_label = "Analyze Seams"
    bl_description = "Non-destructively analyze charts, distortion, and candidate seam cuts"
    bl_options = {"REGISTER"}

    def execute(self, context):
        objects = _selected_visible_mesh_objects(context)
        if not objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}
        settings = _get_settings(context)
        active, selected, mode = _snapshot_context(context)
        chart_count = problem_count = candidate_count = 0
        try:
            _ensure_object_mode()
            for obj in objects:
                result = _analyze_with_temporary_unwrap(obj, settings)
                _CHART_ANALYSIS_CACHE[_mesh_datablock_key(obj)] = result
                chart_count += len(result.charts)
                problem_count += len(result.problem_charts)
                candidate_count += len(result.candidate_seams)
        finally:
            _restore_context(context, active, selected, mode)
        self.report({"INFO"}, iface_("Charts: %d; Problem Charts: %d; Candidate Seams: %d",
                                     chart_count, problem_count, candidate_count))
        return {"FINISHED"}


class AUTOSEAMUV_OT_generate_seams(bpy.types.Operator):
    """Commit a cached or freshly calculated chart seam plan transactionally."""

    bl_idname = "autoseamuv.generate_seams"
    bl_label = "Generate Seams"
    bl_description = "Generate chart-based seams; stale analysis is recalculated automatically"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _selected_visible_mesh_objects(context)
        if not objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}
        settings = _get_settings(context)
        active, selected, mode = _snapshot_context(context)
        changed = processed = 0
        originals = {obj.data.as_pointer(): (obj.data, [edge.use_seam for edge in obj.data.edges])
                     for obj in objects}
        try:
            _ensure_object_mode()
            plans = []
            for obj in objects:
                key = _mesh_datablock_key(obj)
                result = _CHART_ANALYSIS_CACHE.get(key)
                if result is None or result.signature != analysis_signature(obj, settings):
                    result = _analyze_with_temporary_unwrap(obj, settings)
                    _CHART_ANALYSIS_CACHE[key] = result
                plans.append((obj, result))
            # No source seam is touched until every object has analyzed and
            # validated successfully.
            for obj, result in plans:
                changed += apply_chart_seams(obj, result)
                processed += 1
        except Exception as exc:
            for mesh, values in originals.values():
                for edge, value in zip(mesh.edges, values):
                    edge.use_seam = value
                mesh.update()
            self.report({"ERROR"}, iface_("Generate Seams failed: %s", exc))
            return {"CANCELLED"}
        finally:
            _restore_context(context, active, selected, mode)
        self.report({"INFO"}, iface_("Generated %d seam(s) on %d object(s).", changed, processed))
        return {"FINISHED"}


class AUTOSEAMUV_OT_mark_selected_region_boundary(bpy.types.Operator):
    """Mark only the boundary of the current Edit Mode face selection as seams."""

    bl_idname = "autoseamuv.mark_selected_region_boundary"
    bl_label = "Mark Selected Region Boundary as Seam"
    bl_description = "Add UV seams along the boundary of selected faces on the active mesh object"
    bl_options = {"REGISTER", "UNDO"}

    include_open_boundaries: BoolProperty(
        name="Include Open Boundaries",
        description="Include selected faces' edges on the open boundary of the mesh",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        active = context.active_object
        return active is not None and active.type == "MESH" and context.mode == "EDIT_MESH"

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        counts = mark_selected_region_boundary_seams(bm, self.include_open_boundaries)
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        self.report(
            {"INFO"},
            iface_(
                "Selected Face Count: %d; Boundary Edge Count: %d; Newly Marked Seam Count: %d; Open Boundary Count: %d; Skipped Non-Manifold Edge Count: %d.",
                *counts,
            ),
        )
        return {"FINISHED"}


def _selected_edit_face_indices(obj):
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    return [face.index for face in bm.faces if face.select]


def _analyze_object_ring(obj, settings, face_indices=None):
    grid = analyze_ring_topology(obj.data, face_indices)
    return grid, choose_seam(obj.data, grid, settings.ring_seam_mode)


class AUTOSEAMUV_OT_detect_ring_strip(bpy.types.Operator):
    """Validate the currently selected Edit Mode face component."""
    bl_idname = "autoseamuv.detect_ring_strip"
    bl_label = "Detect Ring / Strip"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and context.mode == "EDIT_MESH"

    def execute(self, context):
        obj = context.active_object
        face_indices = _selected_edit_face_indices(obj)
        try:
            grid, seam = _analyze_object_ring(obj, _get_settings(context), face_indices)
        except TopologyError as exc:
            self.report({"ERROR"}, iface_("Ring / Strip: Invalid - %s", exc))
            return {"CANCELLED"}
        self.report({"INFO"}, iface_("Ring / Strip: Valid; Rings %d, Columns %d, Boundaries %d, Seam candidate %s", grid.ring_count, grid.column_count, grid.boundary_count, seam))
        return {"FINISHED"}


class AUTOSEAMUV_OT_unwrap_ring_strip(bpy.types.Operator):
    """Generate loop UVs from a fully validated 3D quad grid."""
    bl_idname = "autoseamuv.unwrap_ring_strip"
    bl_label = "Unwrap Ring / Strip"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        # In Edit Mode this operation is intentionally scoped to the active
        # object's selected face component.  Object Mode retains batch support.
        selected = ([context.active_object] if context.mode == "EDIT_MESH"
                    and context.active_object is not None else _selected_visible_mesh_objects(context))
        if not selected:
            self.report({"ERROR"}, iface_("Ring / Strip: no visible mesh object selected."))
            return {"CANCELLED"}
        settings = _get_settings(context)
        objects, skipped = _objects_for_processing(self, selected, settings.process_shared_mesh_once)
        active, original_selection, mode = _snapshot_context(context)
        edit_face_indices = _selected_edit_face_indices(active) if mode == "EDIT" else None
        completed = 0
        try:
            _ensure_object_mode()
            for obj in objects:
                try:
                    # Analysis, seam choice, and coordinate generation are pure;
                    # the UV layer is not even created until all validation ends.
                    face_indices = edit_face_indices if obj == active and mode == "EDIT" else None
                    grid, seam = _analyze_object_ring(obj, settings, face_indices)
                    coordinates = build_uv_coordinates(obj.data, grid, seam, settings.ring_layout,
                                                       settings.ring_spacing, settings.ring_orientation,
                                                       settings.ring_normalize)
                    layer = obj.data.uv_layers.get(settings.uv_map_name)
                    if layer is None:
                        if not settings.create_uv_if_missing:
                            raise TopologyError(f"UV map '{settings.uv_map_name}' does not exist")
                        layer = obj.data.uv_layers.new(name=settings.uv_map_name)
                    obj.data.uv_layers.active = layer
                    assign_uv_loops(obj.data, layer, coordinates)
                    completed += 1
                    self.report({"INFO"}, iface_("%s: Rings %d, Columns %d, Boundaries %d, Seam %s", obj.name, grid.ring_count, grid.column_count, grid.boundary_count, seam))
                except (TopologyError, ValueError) as exc:
                    self.report({"ERROR"}, iface_("%s: Invalid - %s", obj.name, exc))
        finally:
            _restore_context(context, active, original_selection, mode)
        self.report({"INFO"}, iface_("Ring / Strip: unwrapped %d, skipped shared %d.", completed, skipped))
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
            iface_("Auto Seam UV: shared mesh data skipped for %d object(s): %s", len(skipped_names), ", ".join(skipped_names)),
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
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
                    if settings.seam_mode == "CLASSIC" and settings.longitudinal_seam_helper:
                        total_longitudinal += mark_longitudinal_seam_helper(obj)
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed to mark seams on %s: %s", obj.name, exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Auto Seam UV: marked %d seam(s), longitudinal %d, cleared %d, processed %d, skipped shared %d, failed %d.", total_marked, total_longitudinal, total_cleared, processed, skipped_shared, failures),
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_unwrap_only(bpy.types.Operator):
    """Unwrap selected mesh objects using existing seams."""

    bl_idname = "autoseamuv.unwrap_only"
    bl_label = "Auto Unwrap"
    bl_description = "Unwrap using current seams without applying Weighted Island Layout or Pack Islands"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
                        self.report({"WARNING"}, iface_("Auto Seam UV: skipped %s; mesh has no faces.", obj.name))
                        continue
                    total_straightened += unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.unwrap_margin,
                        settings.average_islands,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
                    )
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed on %s: %s", obj.name, exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Auto Seam UV: unwrapped %d object(s), marked 0 seam(s), straightened %d circular strip island(s), skipped shared %d, failed %d.", processed, total_straightened, skipped_shared, failures),
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_unwrap_selected_faces(bpy.types.Operator):
    """Unwrap only the current Edit Mode face selection."""

    bl_idname = "autoseamuv.unwrap_selected_faces"
    bl_label = "Unwrap Selected Faces"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None and
                context.active_object.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        obj, settings = context.active_object, _get_settings(context)
        try:
            unwrap_selected_faces(obj, settings.uv_map_name,
                                  settings.create_uv_if_missing,
                                  settings.unwrap_method, settings.unwrap_margin)
        except Exception as exc:
            self.report({"ERROR"}, iface_("Unwrap Selected Faces failed: %s", exc))
            return {"CANCELLED"}
        return {"FINISHED"}


def _run_existing_uv_operation(operator, context, operation, action_label):
    """Run a UV-only backend for selected objects and restore all selection state."""
    selected_objects = _selected_visible_mesh_objects(context)
    if not selected_objects:
        operator.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
        return {"CANCELLED"}
    settings = _get_settings(context)
    objects, skipped_shared = _objects_for_processing(
        operator, selected_objects, settings.process_shared_mesh_once
    )
    active, selected, mode = _snapshot_context(context)
    processed = failures = 0
    try:
        _ensure_object_mode()
        for obj in objects:
            try:
                if not obj.data.polygons:
                    continue
                if obj.data.uv_layers.active is None:
                    raise RuntimeError("an active UV map is required")
                operation(obj, settings)
                processed += 1
            except Exception as exc:
                failures += 1
                operator.report({"ERROR"}, iface_("%s: failed on %s: %s", action_label, obj.name, exc))
    finally:
        _restore_context(context, active, selected, mode)
    operator.report(
        {"INFO"},
        iface_("%s: processed %d object(s), skipped shared %d, failed %d.",
               action_label, processed, skipped_shared, failures),
    )
    return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_weighted_island_layout(bpy.types.Operator):
    """Allocate UV space according to world surface area and polygon density."""

    bl_idname = "autoseamuv.weighted_island_layout"
    bl_label = "Weighted Island Layout"
    bl_description = "Allocate UV area by importance and island aspect within the chosen target UV region"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        reports = []
        result = _run_existing_uv_operation(
            self, context, lambda obj, settings: reports.append(weighted_layout_object(
                obj, settings.weighted_density_influence, settings.weighted_scale_mode,
                settings.weighted_texture_size, settings.weighted_padding_pixels,
                settings.weighted_scope, settings.weighted_target_region)), "Weighted Island Layout")
        if reports:
            self.report({"INFO"}, iface_(
                "Weighted Island Layout: Islands %d, Total Surface Area %.6g, Minimum Weight %.6g, Maximum Weight %.6g, UV utilization %.1f%%.",
                sum(item.island_count for item in reports), sum(item.total_surface_area for item in reports),
                min(item.minimum_weight for item in reports), max(item.maximum_weight for item in reports),
                100.0 * sum(item.uv_utilization for item in reports) / len(reports)))
            if any(item.globally_scaled for item in reports):
                self.report({"WARNING"}, iface_("Preserve Texel Density required one global uniform scale to fit the UV space."))
            if any(item.maximum_area_ratio_error > 0.15 for item in reports):
                self.report({"WARNING"}, iface_("Weighted UV area differs from its target by more than 15%."))
        return result


class AUTOSEAMUV_OT_pack_islands(bpy.types.Operator):
    """Pack existing UV islands without changing seams or re-unwrapping."""

    bl_idname = "autoseamuv.pack_islands"
    bl_label = "Pack Islands"
    bl_description = "Packs each selected object independently"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        return _run_existing_uv_operation(self, context, pack_object, "Pack Islands")


class AUTOSEAMUV_OT_auto_unwrap_pack(bpy.types.Operator):
    """Unwrap selected mesh objects and pack UV islands efficiently."""

    bl_idname = "autoseamuv.auto_unwrap_pack"
    bl_label = "Auto Unwrap + Pack"
    bl_description = "Unwrap selected mesh objects using existing settings, then pack UV islands efficiently into the 0-1 UV space"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
                        self.report({"WARNING"}, iface_("Auto Unwrap + Pack: skipped %s; mesh has no faces.", obj.name))
                        continue
                    total_straightened += unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.unwrap_margin,
                        settings.average_islands,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
                    )
                    pack_object(obj, settings)
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed on %s: %s", obj.name, exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Auto Unwrap + Pack: packed %d object(s), straightened %d circular strip island(s), skipped empty %d, skipped shared %d, failed %d.", processed, total_straightened, skipped_empty, skipped_shared, failures),
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
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
                    if settings.seam_mode == "CLASSIC" and settings.longitudinal_seam_helper:
                        total_longitudinal += mark_longitudinal_seam_helper(obj)
                    total_straightened += unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.unwrap_margin,
                        settings.average_islands,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
                    )
                    if settings.pack_islands:
                        pack_object(obj, settings)
                    processed += 1
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed on %s: %s", obj.name, exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Auto Seam UV: marked %d seam(s), longitudinal %d, cleared %d, unwrapped %d, straightened %d circular strip island(s), skipped shared %d, failed %d.", total_marked, total_longitudinal, total_cleared, processed, total_straightened, skipped_shared, failures),
        )
        return {"FINISHED"} if processed else {"CANCELLED"}


class AUTOSEAMUV_OT_atlas_pack_selected_objects(bpy.types.Operator):
    """Pack active UV maps from selected mesh objects into one shared 0-1 atlas."""

    bl_idname = "autoseamuv.atlas_pack_selected_objects"
    bl_label = "Atlas Pack Selected Objects"
    bl_description = "Packs selected mesh objects into one shared UV atlas"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
                        self.report({"WARNING"}, iface_("Atlas Pack Selected Objects: skipped %s; mesh has no faces.", obj.name))
                        continue
                    if settings.atlas_uv_source == "ACTIVE":
                        has_uv = obj.data.uv_layers.active is not None
                    else:
                        has_uv = ensure_uv_layer(obj, settings.uv_map_name, settings.create_uv_if_missing)
                    if not has_uv:
                        failures += 1
                        detail = "active UV map" if settings.atlas_uv_source == "ACTIVE" else f"UV map '{settings.uv_map_name}'"
                        self.report({"WARNING"}, iface_("Atlas Pack Selected Objects: skipped %s; no %s.", obj.name, detail))
                        continue
                    valid_objects.append(obj)
                except Exception as exc:
                    failures += 1
                    self.report({"ERROR"}, iface_("Atlas Pack Selected Objects: failed to prepare %s: %s", obj.name, exc))

            if not valid_objects:
                self.report(
                    {"WARNING"},
                    iface_("Atlas Pack Selected Objects: no valid mesh objects to pack, skipped empty %d, skipped shared %d, failed %d.", skipped_empty, skipped_shared, failures),
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
            self.report({"ERROR"}, iface_("Atlas Pack Selected Objects: failed to atlas pack selected objects: %s", exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Atlas Pack Selected Objects: packed %d object(s), skipped empty %d, skipped shared %d, failed %d.", processed, skipped_empty, skipped_shared, failures),
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
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
                    self.report({"ERROR"}, iface_("Check UV Overlap: failed to inspect %s: %s", obj.name, exc))

            overlap_faces, pair_count = find_overlaps(
                triangles, area_epsilon, settings.overlap_coord_epsilon,
                settings.check_overlap_across_objects,
            )

            _select_overlap_faces(valid_objects, overlap_faces)
            # Selection is deliberately the only visualization: material slots and
            # polygon material indices are never modified by validation.
        finally:
            _restore_validation_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Check UV Overlap: found %d overlapping face(s) in %d pair(s), skipped %d, failed %d.", len(overlap_faces), pair_count, skipped, failed),
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
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
            _restore_validation_context(context, active, selected, mode)
        self.report({"INFO"}, iface_("Clear UV Overlap Highlight: cleared %d selected face(s).", cleared))
        return {"FINISHED"}


class AUTOSEAMUV_OT_clear_seams(bpy.types.Operator):
    """Clear seams from selected mesh objects."""

    bl_idname = "autoseamuv.clear_seams"
    bl_label = "Clear Seams"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = _selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
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
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed to clear seams on %s: %s", obj.name, exc))
        finally:
            _restore_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Auto Seam UV: cleared %d seam(s), processed %d, skipped shared %d, failed %d.", total_cleared, processed, skipped_shared, failures),
        )
        return {"FINISHED"} if processed else {"CANCELLED"}
