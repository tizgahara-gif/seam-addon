"""Texel density and non-destructive UV quality operators."""
import bpy
import bmesh
from .texel_density import measure_object, scale_for_density
from .uv_validation import UVValidationError, validate_object
from .translations import iface_

def _objects(c):return [o for o in c.selected_objects if o.type=='MESH' and o.data.uv_layers.active]
class AUTOSEAMUV_OT_get_texel_density(bpy.types.Operator):
    bl_idname='autoseamuv.get_texel_density';bl_label='Get Texel Density';bl_options={'REGISTER','UNDO'}
    def execute(self,c):
        s=c.scene.autoseamuv_settings; values=[measure_object(o,s.texture_width,s.texture_height,s.texel_unit) for o in _objects(c)]
        if not values:return {'CANCELLED'}
        s.measured_texel_density=sum(values)/len(values);self.report({'INFO'}, iface_("Texel density: %.3f %s", s.measured_texel_density, s.texel_unit.lower()));return {'FINISHED'}
class AUTOSEAMUV_OT_set_texel_density(bpy.types.Operator):
    bl_idname='autoseamuv.set_texel_density';bl_label='Set Texel Density';bl_options={'REGISTER','UNDO'}
    def execute(self,c):
        s=c.scene.autoseamuv_settings
        for obj in _objects(c):
            current=measure_object(obj,s.texture_width,s.texture_height,s.texel_unit); factor=scale_for_density(current,s.target_texel_density);uv=obj.data.uv_layers.active
            loops=[uv.uv[index].vector for index in range(len(uv.uv))]; center=sum(loops,loops[0].copy()*0.0)/len(loops) if loops else None
            if center:
                for point in loops:point[:]=center+(point-center)*factor
            obj.data.update()
        return {'FINISHED'}
class AUTOSEAMUV_OT_validate_uv(bpy.types.Operator):
    bl_idname='autoseamuv.validate_uv';bl_label='Run UV Quality Check';bl_options={'REGISTER','UNDO'}
    bl_description='Checks UV stretch, flipped faces, zero-area faces, summed UV area, and related statistics. Problem faces may be selected in Edit Mode.'
    def execute(self,c):
        s=c.scene.autoseamuv_settings; summaries=[]
        # Unlike texel-density operations, quality validation must inspect and
        # report selected meshes that are missing a usable active UV layer.
        for obj in (o for o in c.selected_objects if o.type == 'MESH'):
            try:
                result=validate_object(obj,s.uv_zero_tolerance,s.stretch_warning_threshold)
            except UVValidationError as exc:
                self.report(
                    {'ERROR'},
                    iface_("UV quality check failed for %s: %s", obj.name, str(exc)),
                )
                continue
            problem_faces = result['flipped'] | result['zero'] | result['stretched']
            if obj.mode == 'EDIT':
                bm = bmesh.from_edit_mesh(obj.data)
                bm.faces.ensure_lookup_table()
                for face in bm.faces:
                    face.select = face.index in problem_faces
                bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
            else:
                for p in obj.data.polygons:
                    p.select = p.index in problem_faces
                obj.data.update()
            summaries.append(iface_("%s: seams %d, flipped %d, zero %d, stretched %d, stretch avg %.2f / max %.2f, summed UV area %.3f", obj.name, sum(e.use_seam for e in obj.data.edges), len(result['flipped']), len(result['zero']), len(result['stretched']), result['average_stretch'], result['max_stretch'], result['summed_uv_area']))
        s.report_summary=' | '.join(summaries) if summaries else iface_('No UV meshes selected');self.report({'INFO'},s.report_summary);return {'FINISHED'} if summaries else {'CANCELLED'}
CLASSES=(AUTOSEAMUV_OT_get_texel_density,AUTOSEAMUV_OT_set_texel_density,AUTOSEAMUV_OT_validate_uv)
