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
from .weighted_layout import (incremental_pack_object, resolve_weighted_padding,
                              rotation_steps_for_mode, shared_weighted_layout,
                              weighted_layout_object)
from .uv_validation import find_overlaps, triangles_from_object
from .ring_topology import TopologyError, analyze_ring_topology
from .ring_uv import assign_uv_loops, build_uv_coordinates, choose_seam
from .translations import iface_
from .uv_protection import (ProtectionError, assert_plan_does_not_modify_finished,
                            has_active_uv_protection, preflight_finished_write,
                            protected_edge_indices,
                            validate_protection_consistency)
from .chart_seam import (PRESETS, cached_uv_analysis_evaluators,
                         uv_chart_quality_from_snapshot, uv_face_distortion_from_snapshot)
from .mesh_utils import selected_visible_mesh_objects
from .mesh_transaction import restore_meshes, rollback_error, snapshot_meshes


REPORT_PREFIX = "Auto Seam UV"
_EDIT_SELECTION_SNAPSHOTS = {}
_CHART_ANALYSIS_CACHE = {}


def resolve_layout_targets(context, require_uv=True):
    """Return the single source of truth used by layout UI and operators."""
    objects = selected_visible_mesh_objects(context)
    ready = [obj for obj in objects if obj.data.polygons and
             (not require_uv or obj.data.uv_layers.active is not None)]
    missing_uv = [obj for obj in objects if not obj.data.polygons or
                  (require_uv and obj.data.uv_layers.active is None)]
    unique_mesh_count = len({_mesh_datablock_key(obj) for obj in objects})
    return {
        "objects": objects, "ready": ready, "missing_uv": missing_uv,
        "target_count": len(objects), "valid_uv_count": len(ready),
        "missing_uv_count": len(missing_uv), "unique_mesh_count": unique_mesh_count,
        "all_ready": bool(objects) and len(ready) == len(objects),
    }


def selected_face_seeds_by_mesh(context, objects=None):
    """Snapshot Edit Mode face seeds for visible operator targets, by Mesh."""
    if context.mode != "EDIT_MESH":
        return {}
    targets = objects if objects is not None else selected_visible_mesh_objects(context)
    target_keys = {_mesh_datablock_key(obj) for obj in targets}
    seeds = {}
    for obj in getattr(context, "objects_in_mode", ()):
        key = _mesh_datablock_key(obj) if obj.type == "MESH" else None
        if key not in target_keys or key in seeds:
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        seeds[key] = frozenset(face.index for face in bm.faces if face.select)
    return seeds


def resolve_atlas_targets(context, settings):
    """Resolve atlas readiness without creating UV layers or changing state."""
    result = resolve_layout_targets(context, require_uv=False)
    missing = []
    ready = []
    for obj in result["objects"]:
        if not obj.data.polygons:
            missing.append(obj)
            continue
        if settings.atlas_uv_source == "ACTIVE":
            has_uv = obj.data.uv_layers.active is not None
        else:
            has_uv = (obj.data.uv_layers.get(settings.uv_map_name) is not None or
                      settings.create_uv_if_missing)
        (ready if has_uv else missing).append(obj)
    result.update(ready=ready, missing_uv=missing, valid_uv_count=len(ready),
                  missing_uv_count=len(missing),
                  all_ready=bool(result["objects"]) and len(ready) == len(result["objects"]))
    return result


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
    else:
        # Object Mode still stores component selection in each Mesh datablock.
        # Operators that temporarily select all faces must not leak that state.
        select_mode = tuple(context.tool_settings.mesh_select_mode)
        for obj in selected_visible_mesh_objects(context):
            mesh_key = obj.data.as_pointer()
            if mesh_key in _EDIT_SELECTION_SNAPSHOTS:
                continue
            mesh = obj.data
            _EDIT_SELECTION_SNAPSHOTS[mesh_key] = (
                mesh,
                {item.index for item in mesh.vertices if item.select},
                {item.index for item in mesh.edges if item.select},
                {item.index for item in mesh.polygons if item.select},
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
    snapshots = list(_EDIT_SELECTION_SNAPSHOTS.values())
    _EDIT_SELECTION_SNAPSHOTS.clear()
    if active is not None and mode == "EDIT" and active.type == "MESH":
        for mesh, vertices, edges, faces, select_mode in snapshots:
            context.tool_settings.mesh_select_mode = select_mode
            bm = bmesh.from_edit_mesh(mesh)
            bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
            for item in bm.verts: item.select = item.index in vertices
            for item in bm.edges: item.select = item.index in edges
            for item in bm.faces: item.select = item.index in faces
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    else:
        for mesh, vertices, edges, faces, select_mode in snapshots:
            context.tool_settings.mesh_select_mode = select_mode
            for item in mesh.vertices: item.select = item.index in vertices
            for item in mesh.edges: item.select = item.index in edges
            for item in mesh.polygons: item.select = item.index in faces
            mesh.update()


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
    if obj.data.uv_layers.active is not None:
        validate_protection_consistency(obj)
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
    try:
        context.collection.objects.link(temp_obj)

        def unwrap_snapshot(cuts):
            for edge in temp_mesh.edges:
                edge.use_seam = edge.index in cuts
            method = PRESETS.get(settings.seam_preset, PRESETS["HARD_SURFACE"]).method
            unwrap_object(temp_obj, "__AutoSeamUV_Temporary__", True, method, "SCALED", 0.0,
                          False, False, 3, 0.0)
            return tuple(item.vector.copy() for item in temp_mesh.uv_layers.active.uv)

        evaluate, distortion = cached_uv_analysis_evaluators(
            unwrap_snapshot,
            lambda snapshot, chart: uv_chart_quality_from_snapshot(
                temp_mesh, snapshot, chart),
            lambda snapshot, chart: uv_face_distortion_from_snapshot(
                temp_mesh, snapshot, chart),
        )
        return analyze_chart_seams(obj, settings, evaluate, distortion)
    finally:
        if temp_obj.name in bpy.data.objects:
            bpy.data.objects.remove(temp_obj, do_unlink=True)
        if temp_mesh.name in bpy.data.meshes:
            bpy.data.meshes.remove(temp_mesh)


class AUTOSEAMUV_OT_analyze_seams(bpy.types.Operator):
    """Analyze provisional charts without changing seams, UVs, or selection."""

    bl_idname = "autoseamuv.analyze_seams"
    bl_label = "Analyze Seams"
    bl_description = "Non-destructively analyze charts, distortion, and candidate seam cuts"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(
            self, selected_visible_mesh_objects(context), settings.process_shared_mesh_once)
        if not objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}
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
        self.report({"INFO"}, iface_("Charts: %d; Problem Charts: %d; Candidate Seams: %d; Skipped Shared: %d",
                                     chart_count, problem_count, candidate_count, skipped_shared))
        return {"FINISHED"}


class AUTOSEAMUV_OT_generate_seams(bpy.types.Operator):
    """Commit a cached or freshly calculated chart seam plan transactionally."""

    bl_idname = "autoseamuv.generate_seams"
    bl_label = "Generate Seams"
    bl_description = "Generate chart-based seams; stale analysis is recalculated automatically"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(
            self, selected_visible_mesh_objects(context), settings.process_shared_mesh_once)
        if not objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}
        active, selected, mode = _snapshot_context(context)
        changed = processed = failures = 0
        try:
            _ensure_object_mode()
            for obj in objects:
                before = snapshot_meshes((obj,))
                try:
                    key = _mesh_datablock_key(obj)
                    result = _CHART_ANALYSIS_CACHE.get(key)
                    if result is None or result.signature != analysis_signature(obj, settings):
                        result = _analyze_with_temporary_unwrap(obj, settings)
                        _CHART_ANALYSIS_CACHE[key] = result
                    changed += apply_chart_seams(obj, result)
                    processed += 1
                except Exception as exc:
                    failures += 1
                    try:
                        restore_meshes(before)
                    except Exception as rollback_exc:
                        exc = rollback_error("Generate Seams", exc, rollback_exc)
                    self.report({"ERROR"}, iface_("Generate Seams failed on %s; restored: %s", obj.name, exc))
        finally:
            _restore_context(context, active, selected, mode)
        self.report({"INFO"}, iface_("Generated %d seam(s) on %d object(s); skipped shared %d, failed %d.",
                                     changed, processed, skipped_shared, failures))
        return {"FINISHED"} if processed else {"CANCELLED"}


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
        obj.update_from_editmode()
        try:
            validate_protection_consistency(obj)
        except ProtectionError as exc:
            self.report({"ERROR"}, iface_(str(exc)))
            return {"CANCELLED"}
        protected = protected_edge_indices(obj.data)
        seam_snapshot = {index: bool(bm.edges[index].seam) for index in protected}
        counts = mark_selected_region_boundary_seams(bm, self.include_open_boundaries)
        for index, state in seam_snapshot.items():
            bm.edges[index].seam = state
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
                    and context.active_object is not None else selected_visible_mesh_objects(context))
        if not selected:
            self.report({"ERROR"}, iface_("Ring / Strip: no visible mesh object selected."))
            return {"CANCELLED"}
        settings = _get_settings(context)
        objects, skipped = _objects_for_processing(self, selected, settings.process_shared_mesh_once)
        active, original_selection, mode = _snapshot_context(context)
        edit_face_indices = _selected_edit_face_indices(active) if mode == "EDIT" else None
        completed = failures = empty = 0
        try:
            _ensure_object_mode()
            for obj in objects:
                if not obj.data.polygons:
                    empty += 1
                    continue
                before = snapshot_meshes((obj,))
                try:
                    # Analysis, seam choice, and coordinate generation are pure;
                    # the UV layer is not even created until all validation ends.
                    face_indices = edit_face_indices if obj == active and mode == "EDIT" else None
                    grid, seam = _analyze_object_ring(obj, settings, face_indices)
                    coordinates = build_uv_coordinates(obj.data, grid, seam, settings.ring_layout,
                                                       settings.ring_spacing, settings.ring_orientation,
                                                       settings.ring_normalize)
                    pending_loops = [loop for face_index in grid.face_indices
                                     for loop in obj.data.polygons[face_index].loop_indices]
                    preflight_finished_write(obj.data, pending_loops)
                    assert_plan_does_not_modify_finished(obj.data, pending_loops)
                    layer = obj.data.uv_layers.get(settings.uv_map_name)
                    if layer is None:
                        if not settings.create_uv_if_missing:
                            raise TopologyError(f"UV map '{settings.uv_map_name}' does not exist")
                        layer = obj.data.uv_layers.new(name=settings.uv_map_name)
                    obj.data.uv_layers.active = layer
                    assign_uv_loops(obj.data, layer, coordinates)
                    completed += 1
                    self.report({"INFO"}, iface_("%s: Rings %d, Columns %d, Boundaries %d, Seam %s", obj.name, grid.ring_count, grid.column_count, grid.boundary_count, seam))
                except Exception as exc:
                    failures += 1
                    try:
                        _ensure_object_mode()
                        restore_meshes(before)
                    except Exception as rollback_exc:
                        exc = rollback_error("Ring / Strip Unwrap", exc, rollback_exc)
                    self.report({"ERROR"}, iface_("%s: Invalid - %s", obj.name, exc))
        finally:
            _restore_context(context, active, original_selection, mode)
        self.report({"INFO"}, iface_("Ring / Strip: unwrapped %d, failed %d, skipped empty %d, skipped shared %d.", completed, failures, empty, skipped))
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
        selected_objects = selected_visible_mesh_objects(context)
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
                before = snapshot_meshes((obj,))
                try:
                    cleared = marked = longitudinal = 0
                    if settings.clear_existing:
                        cleared = clear_seams(obj.data)
                    marked = _auto_mark(obj, settings)
                    if settings.seam_mode == "CLASSIC" and settings.longitudinal_seam_helper:
                        longitudinal = mark_longitudinal_seam_helper(obj)
                    total_cleared += cleared
                    total_marked += marked
                    total_longitudinal += longitudinal
                    processed += 1
                except Exception as exc:
                    failures += 1
                    try:
                        restore_meshes(before)
                    except Exception as rollback_exc:
                        exc = rollback_error("Auto Mark Seams Only", exc, rollback_exc)
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed to mark seams on %s; restored: %s", obj.name, exc))
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
        selected_objects = selected_visible_mesh_objects(context)
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
                        settings.unwrap_margin_method,
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
    """Unwrap complete UV islands seeded by the Edit Mode face selection."""

    bl_idname = "autoseamuv.unwrap_selected_faces"
    bl_label = "Unwrap Selected UV Islands"
    bl_description = (
        "Unwraps complete UV islands on the current active UV map, seeded by the "
        "Edit Mode face selection. Never creates or switches UV maps. The original "
        "component selection is restored after the operation"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return (context.active_object is not None and
                context.active_object.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        obj, settings = context.active_object, _get_settings(context)
        if obj is None or obj.type != "MESH" or obj.data.uv_layers.active is None:
            self.report({"ERROR"}, iface_(
                "Unwrap Selected UV Islands requires an existing active UV map. "
                "Create or select a UV map first."))
            return {"CANCELLED"}
        active, selected_objects, original_mode = _snapshot_context(context)
        try:
            unwrap_selected_faces(obj, settings.unwrap_method, settings.unwrap_margin_method, settings.unwrap_margin)
        except Exception as exc:
            self.report({"ERROR"}, iface_("Unwrap Selected UV Islands failed: %s", exc))
            return {"CANCELLED"}
        finally:
            _restore_context(context, active, selected_objects, original_mode)
        return {"FINISHED"}


def _run_existing_uv_operation(operator, context, operation, action_label, target_objects=None):
    """Run a UV-only backend for selected objects and restore all selection state."""
    preflight = resolve_layout_targets(context)
    selected_objects = target_objects if target_objects is not None else preflight["objects"]
    if not selected_objects:
        operator.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
        return {"CANCELLED"}
    missing_uv_count = sum(not obj.data.polygons or obj.data.uv_layers.active is None
                           for obj in selected_objects)
    if missing_uv_count:
        operator.report({"ERROR"}, iface_(
            "%d selected mesh object(s) have no usable UV map.",
            missing_uv_count))
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
        settings = _get_settings(context)
        if settings.weighted_scope == "SELECTED_FACES" and context.mode != "EDIT_MESH":
            self.report({"ERROR"}, iface_("Selected UV Islands requires Edit Mode."))
            return {"CANCELLED"}
        seeds = selected_face_seeds_by_mesh(context)
        if settings.weighted_scope == "SELECTED_FACES" and not any(seeds.values()):
            self.report({"ERROR"}, iface_("Select at least one face to seed UV islands."))
            return {"CANCELLED"}
        targets = None
        if settings.weighted_scope == "SELECTED_FACES":
            targets = [obj for obj in resolve_layout_targets(context)["objects"]
                       if seeds.get(_mesh_datablock_key(obj))]
        reports = []
        result = _run_existing_uv_operation(
            self, context, lambda obj, settings: reports.append(weighted_layout_object(
                obj, settings.weighted_density_influence, settings.weighted_scale_mode,
                resolve_weighted_padding(settings),
                settings.weighted_scope, settings.weighted_target_region,
                rotation_steps_for_mode(settings.weighted_rotation_mode),
                seeds.get(_mesh_datablock_key(obj)))), "Weighted Island Layout", targets)
        if reports:
            self.report({"INFO"}, iface_(
                "Weighted Island Layout: Islands %d, Rotated Islands: %d, Total Surface Area %.6g, Minimum Weight %.6g, Maximum Weight %.6g, UV utilization %.1f%%.",
                sum(item.island_count for item in reports),
                sum(item.rotated_island_count for item in reports),
                sum(item.total_surface_area for item in reports),
                min(item.minimum_weight for item in reports), max(item.maximum_weight for item in reports),
                100.0 * sum(item.uv_utilization for item in reports) / len(reports)))
            if any(item.globally_scaled for item in reports):
                self.report({"WARNING"}, iface_("Preserve Texel Density required one global uniform scale to fit the UV space."))
            if any(item.maximum_area_ratio_error > 0.15 for item in reports):
                self.report({"WARNING"}, iface_("Weighted UV area differs from its target by more than 15%."))
        return result


class AUTOSEAMUV_OT_shared_weighted_atlas(bpy.types.Operator):
    """Allocate one weighted atlas across all selected visible mesh objects."""

    bl_idname = "autoseamuv.shared_weighted_atlas"
    bl_label = "Shared Weighted Atlas"
    bl_description = "Reallocate UV area globally so all selected objects share one weighted atlas"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = _get_settings(context)
        preflight = resolve_layout_targets(context)
        if not preflight["objects"]:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}
        if not preflight["all_ready"]:
            self.report({"ERROR"}, iface_("%d selected mesh object(s) have no usable UV map.",
                                          preflight["missing_uv_count"]))
            return {"CANCELLED"}
        if preflight["unique_mesh_count"] < 2:
            self.report({"ERROR"}, iface_("Shared Weighted Atlas requires at least two unique mesh targets."))
            return {"CANCELLED"}
        mesh_counts = {}
        for obj in preflight["objects"]:
            mesh_counts[_mesh_datablock_key(obj)] = mesh_counts.get(_mesh_datablock_key(obj), 0) + 1
        if not settings.process_shared_mesh_once and any(count > 1 for count in mesh_counts.values()):
            self.report({"ERROR"}, iface_("Shared Weighted Atlas cannot independently place objects that share the same Mesh datablock. Enable Process Shared Mesh Data Once or make the mesh data single-user."))
            return {"CANCELLED"}
        if settings.weighted_scope == "SELECTED_FACES" and context.mode != "EDIT_MESH":
            self.report({"ERROR"}, iface_("Selected UV Islands requires Edit Mode."))
            return {"CANCELLED"}
        selected_faces = selected_face_seeds_by_mesh(context, preflight["objects"])
        if settings.weighted_scope == "SELECTED_FACES" and not any(selected_faces.values()):
            self.report({"ERROR"}, iface_("Select at least one face to seed UV islands."))
            return {"CANCELLED"}
        representatives = {}
        for obj in sorted(preflight["objects"], key=lambda item: item.name_full):
            representatives.setdefault(_mesh_datablock_key(obj), obj)
        objects = list(representatives.values()) if settings.process_shared_mesh_once else preflight["objects"]
        active, selected, mode = _snapshot_context(context)
        try:
            _ensure_object_mode()
            report = shared_weighted_layout(
                objects, settings.weighted_density_influence, settings.weighted_scale_mode,
                resolve_weighted_padding(settings),
                settings.weighted_scope, settings.weighted_target_region, selected_faces,
                rotation_steps_for_mode(settings.weighted_rotation_mode))
        except Exception as exc:
            self.report({"ERROR"}, iface_("Shared Weighted Atlas failed: %s", exc))
            return {"CANCELLED"}
        finally:
            _restore_context(context, active, selected, mode)
        self.report({"INFO"}, iface_(
            "Shared Weighted Atlas: Mesh Targets %d, Islands %d, Rotated Islands: %d, Total Surface Area %.6g, Minimum Weight %.6g, Maximum Weight %.6g, UV Utilization %.1f%%.",
            len(objects), report.island_count, report.rotated_island_count,
            report.total_surface_area,
            report.minimum_weight, report.maximum_weight, report.uv_utilization * 100.0))
        return {"FINISHED"}


class AUTOSEAMUV_OT_pack_islands(bpy.types.Operator):
    """Pack existing UV islands without changing seams or re-unwrapping."""

    bl_idname = "autoseamuv.pack_islands"
    bl_label = "Pack Islands"
    bl_description = "Packs each selected object independently"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        if any(has_active_uv_protection(obj.data)
               for obj in selected_visible_mesh_objects(context)):
            self.report({"ERROR"}, iface_(
                "Pack Islands cannot preserve UV Protection. Use Weighted Island Layout or Pack Selected Into Free Space, or clear UV Protection first."))
            return {"CANCELLED"}
        return _run_existing_uv_operation(self, context, pack_object, "Pack Islands")


class AUTOSEAMUV_OT_pack_selected_into_free_space(bpy.types.Operator):
    """Pack selected editable islands while treating every other island as fixed."""
    bl_idname = "autoseamuv.pack_selected_into_free_space"
    bl_label = "Pack Selected Into Free Space"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        obj, settings = context.active_object, _get_settings(context)
        if obj is None or obj.type != "MESH" or context.mode != "EDIT_MESH":
            self.report({"ERROR"}, iface_("Pack Selected Into Free Space requires an active mesh in Edit Mode."))
            return {"CANCELLED"}
        if not obj.data.polygons:
            self.report({"ERROR"}, iface_("The active mesh has no faces."))
            return {"CANCELLED"}
        if obj.data.uv_layers.active is None:
            self.report({"ERROR"}, iface_("Pack Selected Into Free Space requires an active UV map."))
            return {"CANCELLED"}
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table(); bm.faces.index_update()
        selected_faces = frozenset(face.index for face in bm.faces if face.select)
        if not selected_faces:
            self.report({"ERROR"}, iface_("Select at least one face to seed UV islands."))
            return {"CANCELLED"}
        # Edit Mesh is authoritative until this point.  From here onward the
        # weighted backend operates exclusively on Object Mode Mesh data.
        active, selected, mode = _snapshot_context(context)
        try:
            _ensure_object_mode()
            report = incremental_pack_object(
                obj, settings.weighted_density_influence, settings.weighted_scale_mode,
                resolve_weighted_padding(settings), settings.weighted_target_region,
                rotation_steps_for_mode(settings.weighted_rotation_mode),
                selected_face_indices=selected_faces)
        except Exception as exc:
            self.report({"ERROR"}, iface_("Pack Selected Into Free Space failed: %s", exc))
            return {"CANCELLED"}
        finally:
            _restore_context(context, active, selected, mode)
        self.report({"INFO"}, iface_("Packed %d selected UV island(s).", report.island_count))
        return {"FINISHED"}


class AUTOSEAMUV_OT_auto_unwrap_pack(bpy.types.Operator):
    """Unwrap selected mesh objects and pack UV islands efficiently."""

    bl_idname = "autoseamuv.auto_unwrap_pack"
    bl_label = "Auto Unwrap + Pack"
    bl_description = "Unwrap selected mesh objects using existing settings, then pack UV islands efficiently into the 0-1 UV space"
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    def execute(self, context):
        selected_objects = selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}

        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(self, selected_objects, settings.process_shared_mesh_once)
        if any(has_active_uv_protection(obj.data) for obj in objects):
            self.report({"ERROR"}, iface_(
                "Auto Unwrap + Pack cannot preserve UV Protection because its Pack stage uses Standard Pack Islands. Use Unwrap and a Protection-aware layout operation separately."))
            return {"CANCELLED"}
        active, selected, mode = _snapshot_context(context)
        processed = 0
        skipped_empty = 0
        failures = 0
        total_straightened = 0

        _warn_non_uniform_scale(self, objects)

        try:
            _ensure_object_mode()
            for obj in objects:
                before = snapshot_meshes((obj,))
                try:
                    if len(obj.data.polygons) == 0:
                        skipped_empty += 1
                        self.report({"WARNING"}, iface_("Auto Unwrap + Pack: skipped %s; mesh has no faces.", obj.name))
                        continue
                    straightened = unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.unwrap_margin_method,
                        settings.unwrap_margin,
                        settings.average_islands,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
                    )
                    pack_object(obj, settings)
                    total_straightened += straightened
                    processed += 1
                except Exception as exc:
                    failures += 1
                    try:
                        restore_meshes(before)
                    except Exception as rollback_exc:
                        exc = rollback_error("Auto Unwrap + Pack", exc, rollback_exc)
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed on %s; restored: %s", obj.name, exc))
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
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    def execute(self, context):
        selected_objects = selected_visible_mesh_objects(context)
        if not selected_objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}

        settings = _get_settings(context)
        objects, skipped_shared = _objects_for_processing(self, selected_objects, settings.process_shared_mesh_once)
        if settings.pack_islands and any(
                has_active_uv_protection(obj.data) for obj in objects):
            self.report({"ERROR"}, iface_(
                "Auto Seam + Unwrap cannot preserve UV Protection while Pack Islands is enabled because its Pack stage uses Standard Pack Islands. Disable Pack Islands, or use a Protection-aware layout operation separately."))
            return {"CANCELLED"}
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
                before = snapshot_meshes((obj,))
                try:
                    cleared = marked = longitudinal = straightened = 0
                    if settings.clear_existing:
                        cleared = clear_seams(obj.data)
                    marked = _auto_mark(obj, settings)
                    if settings.seam_mode == "CLASSIC" and settings.longitudinal_seam_helper:
                        longitudinal = mark_longitudinal_seam_helper(obj)
                    straightened = unwrap_object(
                        obj,
                        settings.uv_map_name,
                        settings.create_uv_if_missing,
                        settings.unwrap_method,
                        settings.unwrap_margin_method,
                        settings.unwrap_margin,
                        settings.average_islands,
                        settings.straighten_circular_strip_islands,
                        settings.circular_strip_min_faces,
                        settings.circular_strip_margin,
                    )
                    if settings.pack_islands:
                        pack_object(obj, settings)
                    total_cleared += cleared
                    total_marked += marked
                    total_longitudinal += longitudinal
                    total_straightened += straightened
                    processed += 1
                except Exception as exc:
                    failures += 1
                    try:
                        restore_meshes(before)
                    except Exception as rollback_exc:
                        exc = rollback_error("Auto Seam + Unwrap", exc, rollback_exc)
                    self.report({"ERROR"}, iface_("Auto Seam UV: failed on %s; restored: %s", obj.name, exc))
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
        settings = _get_settings(context)
        preflight = resolve_atlas_targets(context, settings)
        selected_objects = preflight["objects"]
        if not selected_objects:
            self.report({"WARNING"}, iface_("Auto Seam UV: no visible mesh objects selected."))
            return {"CANCELLED"}
        if not preflight["all_ready"]:
            self.report({"ERROR"}, iface_(
                "%d selected mesh object(s) have no usable UV map.",
                preflight["missing_uv_count"]))
            return {"CANCELLED"}
        if any(has_active_uv_protection(obj.data) for obj in selected_objects):
            self.report({"ERROR"}, iface_(
                "Atlas Pack cannot preserve UV Protection on the selected objects. Use Shared Weighted Atlas or clear UV Protection first."))
            return {"CANCELLED"}
        objects, skipped_shared = _objects_for_processing(self, selected_objects, settings.process_shared_mesh_once)
        active, selected, mode = _snapshot_context(context)
        processed = 0
        skipped_empty = 0
        failures = 0
        valid_objects: list[bpy.types.Object] = []
        before = None

        try:
            _ensure_object_mode()
            # Atlas packing is one cross-object operation: unlike the ordinary
            # operators its transaction intentionally spans every target Mesh.
            before = snapshot_meshes(objects)
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
                    raise RuntimeError(
                        f"failed to prepare {obj.name}: {exc}") from exc

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

            if "FINISHED" not in bpy.ops.object.mode_set(mode="EDIT"):
                raise RuntimeError("could not enter multi-object Edit Mode")
            if "FINISHED" not in bpy.ops.mesh.select_mode(type="FACE"):
                raise RuntimeError("could not select Atlas faces")
            if "FINISHED" not in bpy.ops.mesh.select_all(action="SELECT"):
                raise RuntimeError("could not select all Atlas faces")

            if settings.atlas_average_island_scale:
                if "FINISHED" not in bpy.ops.uv.average_islands_scale():
                    raise RuntimeError("Blender Average Islands Scale was cancelled")

            atlas_margin = settings.atlas_pixel_margin / int(settings.atlas_texture_resolution)
            result = bpy.ops.uv.pack_islands(
                margin=atlas_margin,
                margin_method="FRACTION",
                rotate=settings.atlas_pack_rotate,
            )
            if "FINISHED" not in result:
                raise RuntimeError("Blender Atlas Pack was cancelled")

            processed = len(valid_objects)
        except Exception as exc:
            failures += len(valid_objects) if valid_objects else 1
            if before is not None:
                try:
                    _ensure_object_mode()
                except Exception:
                    pass
                try:
                    restore_meshes(before)
                except Exception as rollback_exc:
                    exc = rollback_error("Atlas Pack Selected Objects", exc, rollback_exc)
                else:
                    exc = RuntimeError(f"{exc}; all target meshes restored")
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
        selected_objects = selected_visible_mesh_objects(context)
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

            overlap_result = find_overlaps(
                triangles, area_epsilon, settings.overlap_coord_epsilon,
                settings.check_overlap_across_objects,
            )
            selected_faces = set(overlap_result.partial_overlaps)
            if settings.select_exact_uv_stacks:
                selected_faces.update(overlap_result.exact_stacks)
            _select_overlap_faces(valid_objects, selected_faces)
            # Selection is deliberately the only visualization: material slots and
            # polygon material indices are never modified by validation.
        finally:
            _restore_validation_context(context, active, selected, mode)

        self.report(
            {"INFO"},
            iface_("Check UV Overlap: selected %d partial-overlap face(s) in %d pair(s); exact stack candidates %d face(s) in %d pair(s); skipped %d, failed %d.",
                   len(overlap_result.partial_overlaps), overlap_result.partial_pair_count,
                   len(overlap_result.exact_stacks), overlap_result.exact_pair_count,
                   skipped, failed),
        )
        return {"FINISHED"} if valid_objects else {"CANCELLED"}


class AUTOSEAMUV_OT_clear_uv_overlap_highlight(bpy.types.Operator):
    """Clear the non-destructive UV overlap face selection."""

    bl_idname = "autoseamuv.clear_uv_overlap_highlight"
    bl_label = "Clear UV Overlap Highlight"
    bl_description = "Clear overlap face selection without changing materials"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected_objects = selected_visible_mesh_objects(context)
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
        selected_objects = selected_visible_mesh_objects(context)
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
                    if obj.data.uv_layers.active is not None:
                        validate_protection_consistency(obj)
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
