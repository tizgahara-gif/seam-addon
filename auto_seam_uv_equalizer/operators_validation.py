"""Texel density and non-destructive UV quality operators."""
import bpy
from .texel_density import measure_object, scale_for_density
from .uv_validation import validate_object
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
    bl_description='Checks UV stretch, flipped faces, zero-area faces, coverage, and related statistics. Problem faces may be selected in Edit Mode.'
    def execute(self,c):
        s=c.scene.autoseamuv_settings; summaries=[]
        for obj in _objects(c):
            result=validate_object(obj,s.uv_zero_tolerance,s.stretch_warning_threshold)
            for p in obj.data.polygons:p.select=p.index in result['flipped']|result['zero']
            summaries.append(iface_("%s: seams %d, flipped %d, zero %d, stretch %.2f/%.2f, coverage %.3f", obj.name, sum(e.use_seam for e in obj.data.edges), len(result['flipped']), len(result['zero']), result['average_stretch'], result['max_stretch'], result['coverage']))
        s.report_summary=' | '.join(summaries) if summaries else iface_('No UV meshes selected');self.report({'INFO'},s.report_summary);return {'FINISHED'} if summaries else {'CANCELLED'}
CLASSES=(AUTOSEAMUV_OT_get_texel_density,AUTOSEAMUV_OT_set_texel_density,AUTOSEAMUV_OT_validate_uv)
