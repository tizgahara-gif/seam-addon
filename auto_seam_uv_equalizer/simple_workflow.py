"""Independent, transactional one-click stages for Simple Mode."""

from __future__ import annotations

from dataclasses import dataclass

import bpy

from . import operators
from .operators_symmetry import transfer_standard_uv_backend
from .seam_detection import CHART_ANALYSIS_SETTING_NAMES
from .symmetry import SymmetryNotFoundError
from .translations import iface_
from .uv_tools import unwrap_object
from .weighted_layout import (rotation_steps_for_mode, shared_weighted_layout,
                              weighted_layout_object)


@dataclass(frozen=True)
class SimpleConfig:
    """Safe Simple defaults, wholly independent of Advanced Scene settings."""
    seam_preset: str = "ORGANIC"
    unwrap_method: str = "ANGLE_BASED"
    unwrap_margin_method: str = "FRACTION"
    unwrap_margin: float = 0.015
    density_influence: float = 0.25
    padding: float = 4.0 / 2048.0
    rotation_mode: str = "STEP_90"
    scale_mode: str = "PRESERVE_TEXEL_DENSITY"
    symmetry_axis: str = "X"
    symmetry_direction: str = "POSITIVE_TO_NEGATIVE"
    symmetry_tolerance: float = 0.0001


@dataclass(frozen=True)
class SimpleTargets:
    selected_objects: tuple
    editable_objects: tuple
    unique_objects: tuple
    selected_count: int
    editable_count: int
    unique_mesh_count: int
    uv_ready_count: int
    missing_uv_count: int
    empty_mesh_count: int
    all_uv_ready: bool


def resolve_simple_targets(context) -> SimpleTargets:
    """Resolve the exact, fixed-policy target set shared by Simple UI/operators."""
    selected = tuple(operators.resolve_layout_targets(
        context, require_uv=False)["objects"])
    editable = tuple(obj for obj in selected if obj.data.polygons)
    unique, seen = [], set()
    for obj in editable:
        key = obj.data.as_pointer()
        if key not in seen:
            seen.add(key)
            unique.append(obj)
    ready = sum(obj.data.uv_layers.active is not None for obj in unique)
    return SimpleTargets(
        selected, editable, tuple(unique), len(selected), len(editable), len(unique),
        ready, len(unique) - ready, len(selected) - len(editable),
        bool(unique) and ready == len(unique))


@dataclass(frozen=True)
class ChartSettings:
    """Typed adapter implementing the chart-analysis settings contract."""
    seam_preset: str
    unwrap_method: str
    max_chart_distortion: float = 0.18
    seam_count_penalty: float = 0.08
    seam_minimum_spacing: int = 3
    straightness_bias: float = 0.6
    preserve_existing_seams: bool = True
    material_boundary: bool = True
    curvature_bias: float = 1.0
    weight_material: float = 1.5
    seam_search_radius: int = 24
    chart_refinement_iterations: int = 5
    character_front_axis: str = "-Y"
    use_professional_garment_prior: bool = True
    mesh_symmetry_axis: str = "X"
    mesh_symmetry_tolerance: float = 0.0001
    use_distortion_guided_candidates: bool = True
    use_edge_loop_completion: bool = True


def _chart_settings(config):
    settings = ChartSettings(seam_preset=config.seam_preset,
                             unwrap_method=config.unwrap_method,
                             mesh_symmetry_axis=config.symmetry_axis,
                             mesh_symmetry_tolerance=config.symmetry_tolerance)
    missing = set(CHART_ANALYSIS_SETTING_NAMES).difference(vars(settings))
    if missing:
        raise TypeError(f"Simple chart settings are missing: {', '.join(sorted(missing))}")
    return settings


def run_chart_seam(obj, config):
    settings = _chart_settings(config)
    return operators.apply_chart_seams(
        obj, operators._analyze_with_temporary_unwrap(obj, settings))


def run_unwrap(obj, config):
    active = obj.data.uv_layers.active
    uv_name = active.name if active is not None else "UVMap"
    return unwrap_object(obj, uv_name, True, config.unwrap_method,
                         config.unwrap_margin_method, config.unwrap_margin,
                         False, False, 3, 0.0)


def _run_unwrap_stage(objects, config):
    for obj in objects:
        run_unwrap(obj, config)
    return len(objects)


def run_weighted_layout(objects, config):
    steps = rotation_steps_for_mode(config.rotation_mode)
    if len(objects) == 1:
        return weighted_layout_object(objects[0], config.density_influence,
                                      config.scale_mode, config.padding,
                                      "WHOLE_OBJECT", "FULL", steps, None)
    return shared_weighted_layout(objects, config.density_influence,
                                  config.scale_mode, config.padding,
                                  "WHOLE_OBJECT", "FULL", {}, steps)


@dataclass(frozen=True)
class SimpleSymmetryReport:
    applied_objects: int
    applied_face_pairs: int
    skipped_objects: tuple


def run_symmetry(objects, config):
    applied_objects, pairs, skipped = 0, 0, []
    for obj in objects:
        try:
            count = transfer_standard_uv_backend(
                obj, config.symmetry_axis, config.symmetry_direction,
                config.symmetry_tolerance, "OVERLAP", 0.02)
        except SymmetryNotFoundError as exc:
            skipped.append((obj.name, str(exc)))
            continue
        applied_objects += 1
        pairs += count
    return SimpleSymmetryReport(applied_objects, pairs, tuple(skipped))


def _snapshot_seams(objects):
    return {obj.data.as_pointer(): (obj.data, tuple(edge.use_seam for edge in obj.data.edges))
            for obj in objects}


def _rollback_seams(snapshot):
    for mesh, seams in snapshot.values():
        if len(mesh.edges) != len(seams):
            raise RuntimeError("mesh topology changed; seam rollback is incomplete")
        for edge, value in zip(mesh.edges, seams):
            edge.use_seam = value
        mesh.update()


def _snapshot_uvs(objects):
    result = {}
    for obj in objects:
        mesh = obj.data
        result[mesh.as_pointer()] = (
            mesh, tuple((layer.name, tuple(tuple(uv.vector) for uv in layer.uv))
                        for layer in mesh.uv_layers),
            mesh.uv_layers.active.name if mesh.uv_layers.active else None)
    return result


def _rollback_uvs(snapshot):
    for mesh, layers, active_name in snapshot.values():
        while len(mesh.uv_layers):
            mesh.uv_layers.remove(mesh.uv_layers[0])
        for name, values in layers:
            layer = mesh.uv_layers.new(name=name)
            if len(layer.uv) != len(values):
                raise RuntimeError("mesh topology changed; UV rollback is incomplete")
            for datum, value in zip(layer.uv, values):
                datum.vector = value
        mesh.uv_layers.active = mesh.uv_layers.get(active_name) if active_name else None
        mesh.update()


def _execute_stage(operator, context, operation, snapshot, rollback, require_uv=False):
    """Run every Simple stage with one transaction ordering contract."""
    active, selected, mode = operators._snapshot_context(context)
    before = None
    targets = None
    try:
        operators._ensure_object_mode()
        targets = resolve_simple_targets(context)
        if not targets.unique_objects:
            operator.report({"ERROR"}, iface_("No editable mesh selected."))
            return {"CANCELLED"}, None, targets
        if require_uv and not targets.all_uv_ready:
            operator.report({"ERROR"}, iface_(
                "%d selected mesh target(s) have no active UV map.",
                targets.missing_uv_count))
            return {"CANCELLED"}, None, targets
        if targets.empty_mesh_count:
            operator.report({"WARNING"}, iface_("Skipped %d empty mesh object(s).",
                                                targets.empty_mesh_count))
        before = snapshot(targets.unique_objects)
        result = operation(targets.unique_objects)
        return {"FINISHED"}, result, targets
    except Exception as exc:
        if before is None:
            operator.report({"ERROR"}, iface_("%s failed: %s", operator.bl_label, exc))
        else:
            try:
                rollback(before)
            except Exception as rollback_exc:
                operator.report({"ERROR"}, iface_(
                    "%s failed; rollback also failed: %s (original error: %s)",
                    operator.bl_label, rollback_exc, exc))
            else:
                operator.report({"ERROR"}, iface_(
                    "%s failed — stage changes rolled back: %s", operator.bl_label, exc))
        return {"CANCELLED"}, None, targets
    finally:
        operators._restore_context(context, active, selected, mode)


class AUTOSEAMUV_OT_simple_auto_seam(bpy.types.Operator):
    bl_idname, bl_label = "autoseamuv.simple_auto_seam", "Auto Seam"
    bl_description = "Chart-Based seam generation using the Organic / Cloth preset"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        config = SimpleConfig()
        status, result, _ = _execute_stage(self, context,
            lambda objects: sum(run_chart_seam(obj, config) for obj in objects),
            _snapshot_seams, _rollback_seams)
        if status == {"FINISHED"}:
            self.report({"INFO"}, iface_("Auto Seam completed: %d seam(s).", result))
        return status


class AUTOSEAMUV_OT_simple_auto_unwrap(bpy.types.Operator):
    bl_idname, bl_label = "autoseamuv.simple_auto_unwrap", "Auto Unwrap"
    bl_description = "Use current seams and the active UV map, or create UVMap if missing"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        config = SimpleConfig()
        status, result, _ = _execute_stage(self, context,
            lambda objects: _run_unwrap_stage(objects, config),
            _snapshot_uvs, _rollback_uvs)
        if status == {"FINISHED"}:
            self.report({"INFO"}, iface_("Auto Unwrap completed for %d object(s).", result))
        return status


class AUTOSEAMUV_OT_simple_auto_layout(bpy.types.Operator):
    bl_idname, bl_label = "autoseamuv.simple_auto_layout", "Auto Layout"
    bl_description = "Scale, rotate, and pack existing UV islands using Weighted Layout"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        config = SimpleConfig()
        status, result, _ = _execute_stage(self, context,
            lambda objects: run_weighted_layout(objects, config),
            _snapshot_uvs, _rollback_uvs, require_uv=True)
        if status == {"FINISHED"}:
            self.report({"INFO"}, iface_("Auto Layout completed: %d island(s).",
                                        result.island_count))
        return status


class AUTOSEAMUV_OT_simple_auto_symmetry(bpy.types.Operator):
    bl_idname, bl_label = "autoseamuv.simple_auto_symmetry", "Auto Symmetry"
    bl_description = "Copy source-side UVs onto the mirrored side; paired islands overlap"
    bl_options = {"REGISTER", "UNDO"}
    def execute(self, context):
        settings = context.scene.autoseamuv_settings
        config = SimpleConfig(symmetry_axis=settings.simple_symmetry_axis,
                              symmetry_direction=settings.simple_symmetry_direction)
        status, report, _ = _execute_stage(self, context,
            lambda objects: run_symmetry(objects, config),
            _snapshot_uvs, _rollback_uvs, require_uv=True)
        if status != {"FINISHED"}:
            return status
        if not report.applied_objects:
            self.report({"WARNING"}, iface_(
                "No selected mesh had valid symmetric topology."))
            return {"CANCELLED"}
        self.report({"INFO"}, iface_(
            "Auto Symmetry: %d object(s) applied, %d skipped (%d face pair(s)).",
            report.applied_objects, len(report.skipped_objects),
            report.applied_face_pairs))
        return status


CLASSES = (AUTOSEAMUV_OT_simple_auto_seam, AUTOSEAMUV_OT_simple_auto_unwrap,
           AUTOSEAMUV_OT_simple_auto_layout, AUTOSEAMUV_OT_simple_auto_symmetry)
