"""User-facing explicit UV protection operators."""
from __future__ import annotations

import bmesh
import bpy

from .translations import iface_
from .uv_protection import (FINISHED_ATTRIBUTE, LAYOUT_LOCK_ATTRIBUTE,
                            ProtectionError, selected_islands)


class _ProtectionTagBase(bpy.types.Operator):
    bl_options = {"REGISTER", "UNDO"}
    kind = ""
    value = True

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH"
                    and obj.data.uv_layers.active is not None)

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table(); bm.faces.index_update()
        selected = {face.index for face in bm.faces if face.select}
        # Mesh connectivity readers need the current Edit Mesh, but selection is
        # only read and is never rewritten.
        obj.update_from_editmode()
        try:
            islands = selected_islands(obj, selected)
            if not islands:
                raise ProtectionError("No selected UV islands found.")
            if self.kind == "finished":
                layer = (bm.faces.layers.int.get(FINISHED_ATTRIBUTE)
                         or bm.faces.layers.int.new(FINISHED_ATTRIBUTE))
                next_group = max((int(face[layer]) for face in bm.faces), default=0) + 1
                for faces in islands:
                    group = next_group if self.value else 0
                    next_group += bool(self.value)
                    for index in faces:
                        bm.faces[index][layer] = group
            else:
                layer = (bm.faces.layers.int.get(LAYOUT_LOCK_ATTRIBUTE)
                         or bm.faces.layers.int.new(LAYOUT_LOCK_ATTRIBUTE))
                for faces in islands:
                    for index in faces:
                        bm.faces[index][layer] = int(bool(self.value))
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            count = len(islands)
        except ProtectionError as exc:
            self.report({"ERROR"}, iface_(str(exc)))
            return {"CANCELLED"}
        if obj.data.users > 1:
            self.report({"INFO"}, iface_("Protection is stored on shared mesh data."))
        self.report({"INFO"}, iface_("Updated protection on %d UV island(s).", count))
        return {"FINISHED"}


class AUTOSEAMUV_OT_mark_finished_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.mark_finished_islands"
    bl_label = "Mark Selected UV Islands Finished"
    kind = "finished"


class AUTOSEAMUV_OT_unmark_finished_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.unmark_finished_islands"
    bl_label = "Unmark Selected UV Islands Finished"
    kind = "finished"; value = False


class AUTOSEAMUV_OT_lock_layout_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.lock_layout_islands"
    bl_label = "Lock Selected UV Islands"
    kind = "layout"


class AUTOSEAMUV_OT_unlock_layout_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.unlock_layout_islands"
    bl_label = "Unlock Selected UV Islands"
    kind = "layout"; value = False


CLASSES = (AUTOSEAMUV_OT_mark_finished_islands,
           AUTOSEAMUV_OT_unmark_finished_islands,
           AUTOSEAMUV_OT_lock_layout_islands,
           AUTOSEAMUV_OT_unlock_layout_islands)
