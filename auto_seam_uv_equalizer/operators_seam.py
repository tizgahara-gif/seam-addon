"""Seam authoring, mirroring, conversion, and group operators."""
from __future__ import annotations
import bpy
import bmesh
from .symmetry import mirror_edge_map
from .seam_groups import save, apply, delete
from .translations import iface_
from .constants import FORCE_SEAM_ATTRIBUTE, PROTECT_SEAM_ATTRIBUTE
from .seam_mirror import seam_state_assignments
from .uv_protection import (ProtectionError, assert_plan_does_not_modify_finished,
                            preflight_finished_write,
                            protected_edge_indices, validate_protection_consistency)

def _active_mesh(context):
    obj=context.active_object
    return obj if obj and obj.type=='MESH' else None

def _tag_selected(context,name,value=True):
    obj=_active_mesh(context)
    if not obj: return 0
    was_edit=obj.mode=='EDIT'
    if was_edit: bpy.ops.object.mode_set(mode='OBJECT')
    attr=obj.data.attributes.get(name) or obj.data.attributes.new(name,'BOOLEAN','EDGE')
    count=0
    for edge in obj.data.edges:
        if edge.select: attr.data[edge.index].value=value; count+=1
    if was_edit: bpy.ops.object.mode_set(mode='EDIT')
    return count

class _TagBase(bpy.types.Operator):
    bl_options={'REGISTER','UNDO'}; attribute=''; bl_description='Applies to selected edges of the active mesh object in Edit Mode.'
    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return bool(obj and obj.type == 'MESH' and context.mode == 'EDIT_MESH')
    def execute(self,context):
        count=_tag_selected(context,self.attribute)
        if not count:
            self.report({'WARNING'}, iface_("No mesh edges are selected.")); return {'CANCELLED'}
        self.report({'INFO'}, iface_("Tagged %d edge(s)", count)); return {'FINISHED'}
class AUTOSEAMUV_OT_force_seam(_TagBase):
    bl_idname='autoseamuv.force_seam'; bl_label='Force Auto Seam'; attribute=FORCE_SEAM_ATTRIBUTE
class AUTOSEAMUV_OT_protect_seam(_TagBase):
    bl_idname='autoseamuv.protect_seam'; bl_label='Protect From Auto Seam'; attribute=PROTECT_SEAM_ATTRIBUTE
class AUTOSEAMUV_OT_clear_edge_tags(bpy.types.Operator):
    bl_idname='autoseamuv.clear_edge_tags'; bl_label='Clear All Tags'; bl_options={'REGISTER','UNDO'}; bl_description='Clears all Auto Seam Force and Protect tags from the active mesh object.'
    def execute(self,context):
        obj=_active_mesh(context)
        if not obj:return {'CANCELLED'}
        for name in (FORCE_SEAM_ATTRIBUTE, PROTECT_SEAM_ATTRIBUTE):
            attr=obj.data.attributes.get(name)
            if attr: obj.data.attributes.remove(attr)
        return {'FINISHED'}
class AUTOSEAMUV_OT_mirror_seams(bpy.types.Operator):
    bl_idname='autoseamuv.mirror_seams'; bl_label='Mirror Seam State'; bl_options={'REGISTER','UNDO'}; bl_description='Copies the seam ON/OFF state from the chosen source side to its mirrored counterpart. Selected edges are the source; selected edges with Seam OFF clear the mirrored seam.'
    def execute(self,context):
        obj=_active_mesh(context); s=context.scene.autoseamuv_settings
        if not obj:return {'CANCELLED'}
        if s.mirror_direction == 'SELECTED' and context.mode != 'EDIT_MESH':
            self.report({'ERROR'}, iface_("Selected Side mirroring requires Edit Mode with selected edges."))
            return {'CANCELLED'}
        axis='XYZ'.index(s.mesh_symmetry_axis); mesh=obj.data
        tolerance=s.mesh_symmetry_tolerance
        edit_mode = context.mode == 'EDIT_MESH'
        if edit_mode:
            bm = bmesh.from_edit_mesh(mesh)
            bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table()
            if s.mirror_direction == 'SELECTED' and not any(edge.select for edge in bm.edges):
                self.report({'WARNING'}, iface_("No mesh edges are selected."))
                return {'CANCELLED'}
            vertices, edges = bm.verts, bm.edges
            coordinates = [tuple(v.co) for v in vertices]
            edge_vertices = [tuple(v.index for v in edge.verts) for edge in edges]
        else:
            bm = None; vertices, edges = mesh.vertices, mesh.edges
            coordinates = [tuple(v.co) for v in vertices]
            edge_vertices = [tuple(e.vertices) for e in edges]
        mapping,skipped=mirror_edge_map(coordinates,edge_vertices,axis,tolerance)
        source_states = {
            edge.index: bool(edge.seam if edit_mode else edge.use_seam)
            for edge in edges
        }
        selected = {edge.index for edge in edges if edit_mode and edge.select}
        midpoints = {}
        for edge in edges:
            if edit_mode:
                midpoints[edge.index] = sum(vertex.co[axis] for vertex in edge.verts) * .5
            else:
                midpoints[edge.index] = sum(vertices[index].co[axis] for index in edge.vertices) * .5
        assignments, conflicts = seam_state_assignments(
            mapping, source_states, midpoints, s.mirror_direction, tolerance, selected,
        )
        try:
            if edit_mode: obj.update_from_editmode()
            validate_protection_consistency(obj)
            preflight_finished_write(mesh, edge_indices=assignments)
            assert_plan_does_not_modify_finished(mesh, edge_indices=assignments)
        except ProtectionError as exc:
            self.report({'ERROR'}, iface_(str(exc))); return {'CANCELLED'}
        changed=0
        for target, source_state in assignments.items():
            target_edge = edges[target]
            if source_states[target] == source_state:
                continue
            if edit_mode: target_edge.seam=source_state
            else: target_edge.use_seam=source_state
            changed+=1
        if edit_mode: bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
        else: mesh.update()
        self.report({'INFO'}, iface_("Synchronized %d seam edge(s); skipped %d ambiguous/unmatched edge(s); skipped %d conflicting selected mirror pair(s).", changed, skipped, conflicts)); return {'FINISHED'}
class AUTOSEAMUV_OT_seams_from_sharp(bpy.types.Operator):
    bl_idname='autoseamuv.seams_from_sharp'; bl_label='Mark Seams From Sharp'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        obj=_active_mesh(context)
        if not obj:return {'CANCELLED'}
        protected = protected_edge_indices(obj.data)
        for e in obj.data.edges:
            if e.index not in protected and e.use_edge_sharp:e.use_seam=True
        obj.data.update();return {'FINISHED'}
class AUTOSEAMUV_OT_sharp_from_seams(bpy.types.Operator):
    bl_idname='autoseamuv.sharp_from_seams'; bl_label='Mark Sharp From Seams'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        obj=_active_mesh(context)
        if not obj:return {'CANCELLED'}
        for e in obj.data.edges:
            if e.use_seam:e.use_edge_sharp=True
        obj.data.update();return {'FINISHED'}
class AUTOSEAMUV_OT_select_seams(bpy.types.Operator):
    bl_idname='autoseamuv.select_seams'; bl_label='Select Seams'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        obj=_active_mesh(context)
        if not obj:return {'CANCELLED'}
        edit=obj.mode=='EDIT'
        if edit:bpy.ops.object.mode_set(mode='OBJECT')
        for e in obj.data.edges:e.select=e.use_seam
        if edit:bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}
class AUTOSEAMUV_OT_select_open_edges(bpy.types.Operator):
    bl_idname='autoseamuv.select_open_edges'; bl_label='Select Open Edges'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        obj=_active_mesh(context)
        if not obj:return {'CANCELLED'}
        edit=obj.mode=='EDIT'
        if edit:bpy.ops.object.mode_set(mode='OBJECT')
        counts=[0]*len(obj.data.edges)
        for p in obj.data.polygons:
            for li in p.loop_indices:counts[obj.data.loops[li].edge_index]+=1
        for e in obj.data.edges:e.select=counts[e.index]==1
        if edit:bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}
class _GroupBase(bpy.types.Operator):
    bl_options={'REGISTER','UNDO'}
    def mesh(self,c):return _active_mesh(c).data if _active_mesh(c) else None
class AUTOSEAMUV_OT_create_seam_group(_GroupBase):
    bl_idname='autoseamuv.create_seam_group';bl_label='Create Seam Group'
    def execute(self,c):
        m=self.mesh(c)
        if not m:return {'CANCELLED'}
        save(m,c.scene.autoseamuv_settings.seam_group_name);return {'FINISHED'}
class AUTOSEAMUV_OT_update_seam_group(AUTOSEAMUV_OT_create_seam_group):
    bl_idname='autoseamuv.update_seam_group';bl_label='Update Seam Group'
class AUTOSEAMUV_OT_apply_seam_group(_GroupBase):
    bl_idname='autoseamuv.apply_seam_group';bl_label='Apply Seam Group'
    def execute(self,c):
        m=self.mesh(c);s=c.scene.autoseamuv_settings
        if not m:return {'CANCELLED'}
        protected = protected_edge_indices(m)
        previous = {index: bool(m.edges[index].use_seam) for index in protected}
        try:apply(m,s.seam_group_name,s.seam_group_apply_mode=='MERGE')
        except KeyError:self.report({'ERROR'}, iface_('Seam group not found'));return {'CANCELLED'}
        for index, state in previous.items(): m.edges[index].use_seam = state
        m.update()
        return {'FINISHED'}
class AUTOSEAMUV_OT_delete_seam_group(_GroupBase):
    bl_idname='autoseamuv.delete_seam_group';bl_label='Delete Seam Group'
    def execute(self,c):
        m=self.mesh(c)
        if not m:return {'CANCELLED'}
        delete(m,c.scene.autoseamuv_settings.seam_group_name);return {'FINISHED'}
CLASSES=(AUTOSEAMUV_OT_force_seam,AUTOSEAMUV_OT_protect_seam,AUTOSEAMUV_OT_clear_edge_tags,AUTOSEAMUV_OT_mirror_seams,AUTOSEAMUV_OT_seams_from_sharp,AUTOSEAMUV_OT_sharp_from_seams,AUTOSEAMUV_OT_select_seams,AUTOSEAMUV_OT_select_open_edges,AUTOSEAMUV_OT_create_seam_group,AUTOSEAMUV_OT_update_seam_group,AUTOSEAMUV_OT_apply_seam_group,AUTOSEAMUV_OT_delete_seam_group)
