"""Independent one-click stages for Simple Mode, using production backends."""

from __future__ import annotations

from dataclasses import dataclass

import bpy

from . import operators
from .operators_symmetry import transfer_standard_uv_backend
from .seam_detection import CHART_ANALYSIS_SETTING_NAMES
from .symmetry import SymmetryError
from .translations import iface_
from .uv_protection import ProtectionError
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


def _chart_settings(config: SimpleConfig) -> ChartSettings:
    """Adapt immutable Simple defaults to the production chart contract."""
    settings = ChartSettings(
        seam_preset=config.seam_preset,
        unwrap_method=config.unwrap_method,
        mesh_symmetry_axis=config.symmetry_axis,
        mesh_symmetry_tolerance=config.symmetry_tolerance,
    )
    # Fail at the adapter boundary, rather than deep inside an analysis run,
    # if the production contract grows without a corresponding Simple field.
    missing = set(CHART_ANALYSIS_SETTING_NAMES).difference(vars(settings))
    if missing:
        raise TypeError(f"Simple chart settings are missing: {', '.join(sorted(missing))}")
    return settings


def run_chart_seam(obj, config: SimpleConfig):
    settings = _chart_settings(config)
    return operators.apply_chart_seams(
        obj, operators._analyze_with_temporary_unwrap(obj, settings))


def run_unwrap(obj, config: SimpleConfig):
    active = obj.data.uv_layers.active
    uv_name = active.name if active is not None else "UVMap"
    return unwrap_object(obj, uv_name, True, config.unwrap_method,
                         config.unwrap_margin_method, config.unwrap_margin,
                         False, False, 3, 0.0)


def _run_unwrap_stage(objects, config: SimpleConfig) -> int:
    for obj in objects:
        run_unwrap(obj, config)
    return len(objects)


def run_weighted_layout(objects, config: SimpleConfig):
    steps = rotation_steps_for_mode(config.rotation_mode)
    if len(objects) == 1:
        return weighted_layout_object(objects[0], config.density_influence,
                                      config.scale_mode, config.padding,
                                      "WHOLE_OBJECT", "FULL", steps, None)
    return shared_weighted_layout(objects, config.density_influence,
                                  config.scale_mode, config.padding,
                                  "WHOLE_OBJECT", "FULL", {}, steps)


def run_symmetry(objects, config: SimpleConfig):
    applied = 0
    for obj in objects:
        try:
            applied += transfer_standard_uv_backend(
                obj, config.symmetry_axis, config.symmetry_direction,
                config.symmetry_tolerance, "OVERLAP", 0.02)
        except (SymmetryError, ProtectionError, ValueError):
            continue
    return applied


def _snapshot_seams(objects):
    return {obj.data.as_pointer(): (obj.data, [edge.use_seam for edge in obj.data.edges])
            for obj in objects}


def _rollback_seams(snapshot):
    for mesh, seams in snapshot.values():
        for edge, value in zip(mesh.edges, seams):
            edge.use_seam = value
        mesh.update()


def _snapshot_uvs(objects):
    result = {}
    for obj in objects:
        mesh = obj.data
        result[mesh.as_pointer()] = (
            mesh,
            [(layer, layer.name, [tuple(uv.vector) for uv in layer.uv])
             for layer in mesh.uv_layers],
            mesh.uv_layers.active.name if mesh.uv_layers.active else None,
        )
    return result


def _rollback_uvs(snapshot):
    for mesh, layers, active_name in snapshot.values():
        original_names = {name for _layer, name, _values in layers}
        for layer in list(mesh.uv_layers):
            if layer.name not in original_names:
                mesh.uv_layers.remove(layer)
        for original_layer, name, values in layers:
            layer = mesh.uv_layers.get(name) or original_layer
            for datum, value in zip(layer.uv, values):
                datum.vector = value
        mesh.uv_layers.active = mesh.uv_layers.get(active_name) if active_name else None
        mesh.update()


def _stage_targets(operator, context, *, require_uv=False):
    settings = context.scene.autoseamuv_settings
    targets = operators.resolve_layout_targets(context, require_uv=require_uv)
    if not targets["objects"]:
        operator.report({"ERROR"}, iface_("No editable mesh selected."))
        return None
    if require_uv and not targets["all_ready"]:
        operator.report({"ERROR"}, iface_("No active UV map."))
        return None
    objects, _skipped = operators._objects_for_processing(
        operator, targets["objects"], settings.process_shared_mesh_once)
    if not objects or any(not obj.data.polygons for obj in objects):
        operator.report({"ERROR"}, iface_("No editable mesh selected."))
        return None
    return objects


def _execute_stage(operator, context, operation, snapshot, rollback, success_message):
    objects = _stage_targets(operator, context)
    if objects is None:
        return {"CANCELLED"}
    before = snapshot(objects)
    active, selected, mode = operators._snapshot_context(context)
    try:
        operators._ensure_object_mode()
        result = operation(objects)
    except Exception as exc:
        rollback(before)
        operator.report({"ERROR"}, iface_("%s failed — stage changes rolled back: %s",
                                         operator.bl_label, exc))
        return {"CANCELLED"}
    finally:
        operators._restore_context(context, active, selected, mode)
    operator.report({"INFO"}, iface_(success_message, result))
    return {"FINISHED"}


class AUTOSEAMUV_OT_simple_auto_seam(bpy.types.Operator):
    bl_idname = "autoseamuv.simple_auto_seam"
    bl_label = "Auto Seam"
    bl_description = "Analyze and generate chart-based seams without changing UVs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        config = SimpleConfig()
        return _execute_stage(
            self, context,
            lambda objects: sum(run_chart_seam(obj, config) for obj in objects),
            _snapshot_seams, _rollback_seams, "Auto Seam completed: %d seam(s).")


class AUTOSEAMUV_OT_simple_auto_unwrap(bpy.types.Operator):
    bl_idname = "autoseamuv.simple_auto_unwrap"
    bl_label = "Auto Unwrap"
    bl_description = "Unwrap with the current seams; never regenerates seams or lays out UVs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        config = SimpleConfig()
        return _execute_stage(
            self, context,
            lambda objects: _run_unwrap_stage(objects, config),
            _snapshot_uvs, _rollback_uvs, "Auto Unwrap completed for %d object(s).")


class AUTOSEAMUV_OT_simple_auto_layout(bpy.types.Operator):
    bl_idname = "autoseamuv.simple_auto_layout"
    bl_label = "Auto Layout"
    bl_description = "Lay out existing UV islands without changing seams or unwrapping"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _stage_targets(self, context, require_uv=True)
        if objects is None:
            return {"CANCELLED"}
        config = SimpleConfig()
        before = _snapshot_uvs(objects)
        active, selected, mode = operators._snapshot_context(context)
        try:
            operators._ensure_object_mode()
            report = run_weighted_layout(objects, config)
        except Exception as exc:
            _rollback_uvs(before)
            self.report({"ERROR"}, iface_("Auto Layout failed — stage changes rolled back: %s", exc))
            return {"CANCELLED"}
        finally:
            operators._restore_context(context, active, selected, mode)
        self.report({"INFO"}, iface_("Auto Layout completed: %d island(s).", report.island_count))
        return {"FINISHED"}


class AUTOSEAMUV_OT_simple_auto_symmetry(bpy.types.Operator):
    bl_idname = "autoseamuv.simple_auto_symmetry"
    bl_label = "Auto Symmetry"
    bl_description = "Apply Standard UV Transfer without seam, unwrap, or layout operations"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        objects = _stage_targets(self, context, require_uv=True)
        if objects is None:
            return {"CANCELLED"}
        direction = context.scene.autoseamuv_settings.simple_symmetry_direction
        config = SimpleConfig(symmetry_direction=direction)
        before = _snapshot_uvs(objects)
        active, selected, mode = operators._snapshot_context(context)
        try:
            operators._ensure_object_mode()
            applied = run_symmetry(objects, config)
        except Exception as exc:
            _rollback_uvs(before)
            self.report({"ERROR"}, iface_("Auto Symmetry failed — stage changes rolled back: %s", exc))
            return {"CANCELLED"}
        finally:
            operators._restore_context(context, active, selected, mode)
        if applied:
            self.report({"INFO"}, iface_("Auto Symmetry applied: %d face pair(s).", applied))
        else:
            self.report({"INFO"}, iface_("Skipped — no valid mirrored topology found"))
        return {"FINISHED"}


CLASSES = (
    AUTOSEAMUV_OT_simple_auto_seam,
    AUTOSEAMUV_OT_simple_auto_unwrap,
    AUTOSEAMUV_OT_simple_auto_layout,
    AUTOSEAMUV_OT_simple_auto_symmetry,
)
