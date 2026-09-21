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
            self.report({"INFO"}, iface_("UV protection is stored on shared mesh data."))
        messages = {
            ("finished", True): "Marked %d UV islands as Finished.",
            ("finished", False): "Removed Finished state from %d UV islands.",
            ("layout", True): "Locked layout for %d UV islands.",
            ("layout", False): "Unlocked layout for %d UV islands.",
        }
        self.report({"INFO"}, iface_(messages[(self.kind, self.value)], count))
        return {"FINISHED"}


class AUTOSEAMUV_OT_mark_finished_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.mark_finished_islands"
    bl_label = "Mark Finished"
    bl_description = "Protect selected UV islands from automatic seam, unwrap, and layout changes"
    kind = "finished"


class AUTOSEAMUV_OT_unmark_finished_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.unmark_finished_islands"
    bl_label = "Unmark Finished"
    bl_description = "Remove Finished protection from selected UV islands"
    kind = "finished"; value = False


class AUTOSEAMUV_OT_lock_layout_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.lock_layout_islands"
    bl_label = "Lock Layout"
    bl_description = "Keep selected UV islands' position, rotation, and scale during layout and packing"
    kind = "layout"


class AUTOSEAMUV_OT_unlock_layout_islands(_ProtectionTagBase):
    bl_idname = "autoseamuv.unlock_layout_islands"
    bl_label = "Unlock Layout"
    bl_description = "Remove layout-only protection from selected UV islands"
    kind = "layout"; value = False


class _SelectProtectedBase(bpy.types.Operator):
    bl_options = {"REGISTER", "UNDO"}
    attribute_name = ""

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == "MESH" and context.mode == "EDIT_MESH")

    def execute(self, context):
        obj = context.active_object
        bm = bmesh.from_edit_mesh(obj.data)
        layer = bm.faces.layers.int.get(self.attribute_name)
        for face in bm.faces:
            face.select = bool(layer and int(face[layer]) != 0)
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return {"FINISHED"}


class AUTOSEAMUV_OT_select_finished_islands(_SelectProtectedBase):
    bl_idname = "autoseamuv.select_finished_islands"
    bl_label = "Select Finished"
    attribute_name = FINISHED_ATTRIBUTE


class AUTOSEAMUV_OT_select_layout_locked_islands(_SelectProtectedBase):
    bl_idname = "autoseamuv.select_layout_locked_islands"
    bl_label = "Select Layout Locked"
    attribute_name = LAYOUT_LOCK_ATTRIBUTE


class AUTOSEAMUV_OT_clear_uv_protection(bpy.types.Operator):
    bl_idname = "autoseamuv.clear_uv_protection"
    bl_label = "Clear UV Protection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return {"CANCELLED"}
        bm = bmesh.from_edit_mesh(obj.data) if context.mode == "EDIT_MESH" else None
        if bm:
            for name in (FINISHED_ATTRIBUTE, LAYOUT_LOCK_ATTRIBUTE):
                layer = bm.faces.layers.int.get(name)
                if layer:
                    for face in bm.faces:
                        face[layer] = 0
            bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        else:
            for name in (FINISHED_ATTRIBUTE, LAYOUT_LOCK_ATTRIBUTE):
                attribute = obj.data.attributes.get(name)
                if attribute:
                    for value in attribute.data:
                        value.value = 0
            obj.data.update()
        return {"FINISHED"}


CLASSES = (AUTOSEAMUV_OT_mark_finished_islands,
           AUTOSEAMUV_OT_unmark_finished_islands,
           AUTOSEAMUV_OT_lock_layout_islands,
           AUTOSEAMUV_OT_unlock_layout_islands,
           AUTOSEAMUV_OT_select_finished_islands,
           AUTOSEAMUV_OT_select_layout_locked_islands,
           AUTOSEAMUV_OT_clear_uv_protection)
