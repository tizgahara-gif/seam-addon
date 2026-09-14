"""Seam authoring, mirroring, conversion, and group operators."""
from __future__ import annotations
import bpy
from .symmetry import mirror_edge_map
from .seam_groups import save, apply, delete
from .translations import iface_
from .constants import FORCE_SEAM_ATTRIBUTE, PROTECT_SEAM_ATTRIBUTE

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
    bl_options={'REGISTER','UNDO'}; attribute=''
    def execute(self,context):
        count=_tag_selected(context,self.attribute)
        self.report({'INFO'}, iface_("Tagged %d edge(s)", count)); return {'FINISHED'} if count else {'CANCELLED'}
class AUTOSEAMUV_OT_force_seam(_TagBase):
    bl_idname='autoseamuv.force_seam'; bl_label='Force Auto Seam'; attribute=FORCE_SEAM_ATTRIBUTE
class AUTOSEAMUV_OT_protect_seam(_TagBase):
    bl_idname='autoseamuv.protect_seam'; bl_label='Protect From Auto Seam'; attribute=PROTECT_SEAM_ATTRIBUTE
class AUTOSEAMUV_OT_clear_edge_tags(bpy.types.Operator):
    bl_idname='autoseamuv.clear_edge_tags'; bl_label='Clear Auto Seam Tags'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        obj=_active_mesh(context)
        if not obj:return {'CANCELLED'}
        for name in (FORCE_SEAM_ATTRIBUTE, PROTECT_SEAM_ATTRIBUTE):
            attr=obj.data.attributes.get(name)
            if attr: obj.data.attributes.remove(attr)
        return {'FINISHED'}
class AUTOSEAMUV_OT_mirror_seams(bpy.types.Operator):
    bl_idname='autoseamuv.mirror_seams'; bl_label='Mirror Seams'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        obj=_active_mesh(context); s=context.scene.autoseamuv_settings
        if not obj:return {'CANCELLED'}
        axis='XYZ'.index(s.mirror_axis); mesh=obj.data
        mapping,skipped=mirror_edge_map([tuple(v.co) for v in mesh.vertices],[tuple(e.vertices) for e in mesh.edges],axis,s.mirror_tolerance)
        changed=0
        for source,target in mapping.items():
            mid=(mesh.vertices[mesh.edges[source].vertices[0]].co[axis]+mesh.vertices[mesh.edges[source].vertices[1]].co[axis])*.5
            allowed=(s.mirror_direction=='SELECTED' and mesh.edges[source].select) or (s.mirror_direction=='POSITIVE' and mid>s.mirror_tolerance) or (s.mirror_direction=='NEGATIVE' and mid < -s.mirror_tolerance) or abs(mid)<=s.mirror_tolerance
            if allowed and mesh.edges[source].use_seam and not mesh.edges[target].use_seam: mesh.edges[target].use_seam=True; changed+=1
        mesh.update(); self.report({'INFO'}, iface_("Mirrored %d; skipped %d ambiguous/unmatched edge(s)", changed, skipped)); return {'FINISHED'}
class AUTOSEAMUV_OT_seams_from_sharp(bpy.types.Operator):
    bl_idname='autoseamuv.seams_from_sharp'; bl_label='Mark Seams From Sharp'; bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        obj=_active_mesh(context)
        if not obj:return {'CANCELLED'}
        for e in obj.data.edges:
            if e.use_edge_sharp:e.use_seam=True
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
        try:apply(m,s.seam_group_name,s.seam_group_apply_mode=='MERGE')
        except KeyError:self.report({'ERROR'}, iface_('Seam group not found'));return {'CANCELLED'}
        return {'FINISHED'}
class AUTOSEAMUV_OT_delete_seam_group(_GroupBase):
    bl_idname='autoseamuv.delete_seam_group';bl_label='Delete Seam Group'
    def execute(self,c):
        m=self.mesh(c)
        if not m:return {'CANCELLED'}
        delete(m,c.scene.autoseamuv_settings.seam_group_name);return {'FINISHED'}
CLASSES=(AUTOSEAMUV_OT_force_seam,AUTOSEAMUV_OT_protect_seam,AUTOSEAMUV_OT_clear_edge_tags,AUTOSEAMUV_OT_mirror_seams,AUTOSEAMUV_OT_seams_from_sharp,AUTOSEAMUV_OT_sharp_from_seams,AUTOSEAMUV_OT_select_seams,AUTOSEAMUV_OT_select_open_edges,AUTOSEAMUV_OT_create_seam_group,AUTOSEAMUV_OT_update_seam_group,AUTOSEAMUV_OT_apply_seam_group,AUTOSEAMUV_OT_delete_seam_group)
