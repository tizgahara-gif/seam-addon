"""Focused UV-coordinate-only operators."""

from __future__ import annotations

import bmesh
import bpy

from .translations import iface_
from .uv_island_flip import (
    apply_uv_plan,
    collect_selected_uv_islands,
    plan_horizontal_uv_flip,
)
from .uv_protection import (ProtectionError, assert_plan_does_not_modify_finished,
                            preflight_finished_write,
                            validate_protection_consistency)


class AUTOSEAMUV_OT_flip_selected_uv_islands(bpy.types.Operator):
    """Flip each selected UV island in place around its own U center."""

    bl_idname = "autoseamuv.flip_selected_uv_islands"
    bl_label = "Flip Selected UV Islands"
    bl_description = (
        "Flips each selected UV island horizontally around its own UV bounding-box center. "
        "The islands stay in place."
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH" or context.mode != "EDIT_MESH":
            self.report({"ERROR"}, iface_("Flip Selected UV Islands requires Edit Mode."))
            return {"CANCELLED"}

        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None or mesh.uv_layers.active is None:
            self.report({"ERROR"}, iface_("No active UV map."))
            return {"CANCELLED"}

        # Synchronize the read-only Mesh view consumed by the shared island
        # connectivity helper.  This does not leave Edit Mode or alter selection.
        obj.update_from_editmode()
        islands = collect_selected_uv_islands(obj, bm, uv_layer)
        if not islands:
            self.report({"WARNING"}, iface_("No selected UV islands found."))
            return {"CANCELLED"}
        try:
            planned_uvs = plan_horizontal_uv_flip(islands)
            validate_protection_consistency(obj)
            preflight_finished_write(obj.data, planned_uvs)
            assert_plan_does_not_modify_finished(obj.data, planned_uvs)
        except (ProtectionError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        apply_uv_plan(bm, uv_layer, planned_uvs)
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        self.report({"INFO"}, iface_("Flipped %d UV island(s).", len(islands)))
        return {"FINISHED"}


CLASSES = (AUTOSEAMUV_OT_flip_selected_uv_islands,)
