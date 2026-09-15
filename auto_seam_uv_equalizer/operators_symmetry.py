"""Validation and active-map UV transfer operators."""
from __future__ import annotations

import bmesh
import bpy

from .symmetry import (SymmetryError, build_symmetry_plan, exact_texture_x_uvs,
                       transferred_uvs)
from .translations import iface_
from .operators import _restore_context, _snapshot_context


def _selected_faces(obj):
    if obj.mode == "EDIT":
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table(); bm.faces.index_update()
        return {face.index for face in bm.faces if face.select}
    return {face.index for face in obj.data.polygons if face.select}


def _source_faces(mesh, candidates, axis, sign, tolerance):
    result = []
    for index in candidates:
        coordinates = [float(mesh.vertices[v].co[axis]) * sign for v in mesh.polygons[index].vertices]
        if any(value < -tolerance for value in coordinates) and any(value > tolerance for value in coordinates):
            raise SymmetryError(f"face {index} crosses the symmetry plane")
        if any(value > tolerance for value in coordinates) and not any(value < -tolerance for value in coordinates):
            result.append(index)
    return result


def _plan(context, require_uv):
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        raise SymmetryError("active object is not a mesh")
    settings, mesh = context.scene.autoseamuv_settings, obj.data
    if settings.symmetry_scope == "SELECTED" and context.mode != "EDIT_MESH":
        raise SymmetryError("Selected Faces symmetry requires Edit Mode.")
    layer = mesh.uv_layers.active
    if require_uv and layer is None:
        raise SymmetryError("active UV map does not exist")
    selected = _selected_faces(obj)
    candidates = selected if settings.symmetry_scope == "SELECTED" else range(len(mesh.polygons))
    if settings.symmetry_scope == "SELECTED" and not selected:
        raise SymmetryError("no faces selected")
    axis = "XYZ".index(settings.mesh_symmetry_axis)
    sign = -1 if settings.symmetry_direction == "NEGATIVE_TO_POSITIVE" else 1
    sources = _source_faces(mesh, candidates, axis, sign, settings.mesh_symmetry_tolerance)
    plan = build_symmetry_plan(
        [tuple(vertex.co) for vertex in mesh.vertices],
        [tuple(edge.vertices) for edge in mesh.edges],
        [tuple(face.vertices) for face in mesh.polygons], sources,
        axis, sign, settings.mesh_symmetry_tolerance,
    )
    return obj, layer, plan


class AUTOSEAMUV_OT_validate_symmetry(bpy.types.Operator):
    bl_idname = "autoseamuv.validate_symmetry"
    bl_label = "Validate Symmetry"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.autoseamuv_settings
        if settings.symmetry_scope == "SELECTED" and context.mode != "EDIT_MESH":
            self.report({"ERROR"}, iface_("Selected Faces symmetry requires Edit Mode."))
            return {"CANCELLED"}
        try:
            obj, _layer, plan = _plan(context, False)
        except (SymmetryError, ValueError) as exc:
            self.report({"ERROR"}, iface_("Symmetry validation failed: %s", exc))
            return {"CANCELLED"}
        self.report({"INFO"}, iface_("%s: symmetry valid for %d face pair(s)", obj.name, len(plan.face_pairs)))
        return {"FINISHED"}


class AUTOSEAMUV_OT_transfer_symmetric_uv(bpy.types.Operator):
    bl_idname = "autoseamuv.transfer_symmetric_uv"
    bl_label = "Transfer Symmetric UV"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.autoseamuv_settings
        if settings.symmetry_scope == "SELECTED" and context.mode != "EDIT_MESH":
            self.report({"ERROR"}, iface_("Selected Faces symmetry requires Edit Mode."))
            return {"CANCELLED"}
        obj = context.active_object
        active, selected_objects, original_mode = _snapshot_context(context)
        try:
            if original_mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            obj, layer, plan = _plan(context, True)
            settings = context.scene.autoseamuv_settings
            source_uvs = [tuple(item.vector) for item in layer.uv]
            writes = transferred_uvs(source_uvs, plan.loop_pairs,
                                      settings.symmetry_layout, settings.symmetry_island_gap)
            # This is the first mutation: every geometry/loop/UV check succeeded.
            for loop_index, uv in writes.items():
                layer.uv[loop_index].vector = uv
            obj.data.update()
        except (SymmetryError, ValueError) as exc:
            self.report({"ERROR"}, iface_("Symmetric UV transfer failed: %s", exc))
            return_value = {"CANCELLED"}
        else:
            self.report({"INFO"}, iface_("Transferred %d symmetric UV face pair(s)", len(plan.face_pairs)))
            return_value = {"FINISHED"}
        finally:
            _restore_context(context, active, selected_objects, original_mode)
        return return_value


class AUTOSEAMUV_OT_transfer_exact_texture_x_symmetry(bpy.types.Operator):
    bl_idname = "autoseamuv.transfer_exact_texture_x_symmetry"
    bl_label = "Transfer Exact Texture-X Symmetric UV"
    bl_options = {"REGISTER", "UNDO"}

    _EPSILON = 1.0e-7

    def execute(self, context):
        settings = context.scene.autoseamuv_settings
        if settings.symmetry_scope == "SELECTED" and context.mode != "EDIT_MESH":
            self.report({"ERROR"}, iface_("Selected Faces symmetry requires Edit Mode."))
            return {"CANCELLED"}
        active, selected_objects, original_mode = _snapshot_context(context)
        try:
            if original_mode == "EDIT":
                bpy.ops.object.mode_set(mode="OBJECT")
            obj, layer, plan = _plan(context, True)
            source_uvs = [tuple(item.vector) for item in layer.uv]
            writes = exact_texture_x_uvs(
                source_uvs, plan.loop_pairs,
                context.scene.autoseamuv_settings.texture_source_side,
                self._EPSILON,
            )

            # Retain every destination value so even assignment or post-check
            # failures leave the active map exactly as it was before execution.
            previous = {loop_index: tuple(layer.uv[loop_index].vector)
                        for loop_index in writes}
            try:
                for loop_index, uv in writes.items():
                    layer.uv[loop_index].vector = uv
                for source_loop, destination_loop in plan.loop_pairs:
                    source_uv = layer.uv[source_loop].vector
                    destination_uv = layer.uv[destination_loop].vector
                    if (abs((source_uv.x + destination_uv.x) - 1.0) > self._EPSILON
                            or abs(source_uv.y - destination_uv.y) > self._EPSILON):
                        raise SymmetryError("exact Texture-X post-validation failed")
            except Exception:
                for loop_index, uv in previous.items():
                    layer.uv[loop_index].vector = uv
                obj.data.update()
                raise
            obj.data.update()
        except (SymmetryError, ValueError) as exc:
            self.report({"ERROR"}, iface_(str(exc)))
            return_value = {"CANCELLED"}
        except Exception as exc:
            # A write-time Blender error has already been rolled back above.
            self.report({"ERROR"}, iface_("Exact Texture-X UV transfer failed: %s", str(exc)))
            return_value = {"CANCELLED"}
        else:
            self.report({"INFO"}, iface_(
                "Transferred %d exact Texture-X symmetric UV face pair(s)",
                len(plan.face_pairs)))
            return_value = {"FINISHED"}
        finally:
            _restore_context(context, active, selected_objects, original_mode)
        return return_value


CLASSES = (AUTOSEAMUV_OT_validate_symmetry, AUTOSEAMUV_OT_transfer_symmetric_uv,
           AUTOSEAMUV_OT_transfer_exact_texture_x_symmetry)
