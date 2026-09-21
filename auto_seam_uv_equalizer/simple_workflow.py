"""One-click Simple workflow composed exclusively from production backends."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import bpy

from . import operators
from .operators_symmetry import transfer_standard_uv_backend
from .symmetry import SymmetryError
from .translations import iface_
from .uv_tools import unwrap_object
from .weighted_layout import (rotation_steps_for_mode, shared_weighted_layout,
                              weighted_layout_object)
from .uv_protection import ProtectionError


@dataclass(frozen=True)
class SimpleConfig:
    """Safe defaults kept separate from every Advanced Scene property."""

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


def _chart_settings(config):
    # analyze_chart_seams consumes these established Advanced backend knobs.
    return SimpleNamespace(
        seam_mode="ADVANCED", seam_preset=config.seam_preset,
        preserve_existing_seams=True, clear_existing=False,
        use_professional_garment_prior=True,
        use_distortion_guided_candidates=True, use_edge_loop_completion=True,
        max_chart_distortion=0.18, seam_count_penalty=0.08,
        seam_minimum_spacing=3, straightness_bias=0.6, curvature_bias=1.0,
        seam_search_radius=24, chart_refinement_iterations=5,
        material_boundary=True, weight_material=1.5,
        character_front_axis="-Y", mesh_symmetry_axis="X",
        mesh_symmetry_tolerance=config.symmetry_tolerance,
    )


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


def run_weighted_layout(objects, config):
    steps = rotation_steps_for_mode(config.rotation_mode)
    if len(objects) == 1:
        return weighted_layout_object(objects[0], config.density_influence,
                                      config.scale_mode, config.padding,
                                      "WHOLE_OBJECT", "FULL", steps, None)
    return shared_weighted_layout(objects, config.density_influence,
                                  config.scale_mode, config.padding,
                                  "WHOLE_OBJECT", "FULL", {}, steps)


def run_symmetry(objects, config):
    applied = 0
    for obj in objects:
        try:
            applied += transfer_standard_uv_backend(
                obj, config.symmetry_axis, config.symmetry_direction,
                config.symmetry_tolerance, "OVERLAP", 0.02)
        except (SymmetryError, ProtectionError, ValueError):
            continue
    return applied


def _snapshot(objects):
    result = {}
    for obj in objects:
        mesh = obj.data
        result[mesh.as_pointer()] = (
            mesh, [edge.use_seam for edge in mesh.edges],
            [(layer, layer.name, [tuple(uv.vector) for uv in layer.uv])
             for layer in mesh.uv_layers],
            mesh.uv_layers.active.name if mesh.uv_layers.active else None)
    return result


def _rollback(snapshot):
    for mesh, seams, layers, active_name in snapshot.values():
        for edge, value in zip(mesh.edges, seams):
            edge.use_seam = value
        original_names = {name for _layer, name, _values in layers}
        for layer in list(mesh.uv_layers):
            if layer.name not in original_names:
                mesh.uv_layers.remove(layer)
        for original_layer, name, values in layers:
            # Production backends never delete an existing layer. Keeping its
            # RNA object also retains pin/selection/render metadata on rollback.
            layer = mesh.uv_layers.get(name) or original_layer
            for datum, value in zip(layer.uv, values):
                datum.vector = value
        if active_name:
            mesh.uv_layers.active = mesh.uv_layers.get(active_name)
        mesh.update()


class AUTOSEAMUV_OT_simple_auto_uv(bpy.types.Operator):
    """Create initial UVs through the existing Seam/Unwrap/Layout/Symmetry engines."""

    bl_idname = "autoseamuv.simple_auto_uv"
    bl_label = "Auto UV Setup"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.autoseamuv_settings
        targets = operators.resolve_layout_targets(context, require_uv=False)["objects"]
        objects, _skipped = operators._objects_for_processing(
            self, targets, settings.process_shared_mesh_once)
        if not objects or any(not obj.data.polygons for obj in objects):
            settings.simple_status = iface_("Auto UV Setup failed — no editable mesh selected")
            self.report({"ERROR"}, settings.simple_status)
            return {"CANCELLED"}
        config = SimpleConfig()
        before = _snapshot(objects)
        active, selected, mode = operators._snapshot_context(context)
        try:
            operators._ensure_object_mode()
            for obj in objects:
                run_chart_seam(obj, config)
            for obj in objects:
                run_unwrap(obj, config)
            run_weighted_layout(objects, config)
            symmetry = (run_symmetry(objects, config)
                        if settings.simple_symmetry == "AUTO" else 0)
        except Exception as exc:
            _rollback(before)
            settings.simple_status = iface_("Auto UV Setup failed — changes rolled back: %s", exc)
            self.report({"ERROR"}, settings.simple_status)
            result = {"CANCELLED"}
        else:
            symmetry_text = (iface_("Applied") if symmetry else
                             iface_("Skipped — no valid mirrored topology found"))
            settings.simple_status = iface_(
                "Auto UV Setup completed — Seam: Success; Unwrap: Success; Layout: Success; Symmetry: %s",
                symmetry_text)
            self.report({"INFO"}, settings.simple_status)
            result = {"FINISHED"}
        finally:
            operators._restore_context(context, active, selected, mode)
        return result


CLASSES = (AUTOSEAMUV_OT_simple_auto_uv,)
