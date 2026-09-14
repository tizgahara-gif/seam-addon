"""Task-oriented Blender 5.1 sidebar UI."""
import bpy
class AUTOSEAMUV_PT_panel(bpy.types.Panel):
    bl_idname='AUTOSEAMUV_PT_panel';bl_label='Auto Seam UV';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Auto UV'
    def draw(self,context):self.layout.label(text='UV initial processing and review')
class _Sub:
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='Auto UV';bl_parent_id='AUTOSEAMUV_PT_panel'
class AUTOSEAMUV_PT_auto_seam(_Sub,bpy.types.Panel):
    bl_idname='AUTOSEAMUV_PT_auto_seam';bl_label='Auto Seam'
    def draw(self,c):
        l=self.layout;s=c.scene.autoseamuv_settings;l.prop(s,'seam_preset');l.prop(s,'seam_mode')
        if s.seam_mode=='ADVANCED':
            box=l.box();box.label(text='Candidate & Path Settings');
            for p in ('seam_search_radius','seam_minimum_spacing','straightness_bias','curvature_bias','existing_seam_attraction','boundary_attraction'):box.prop(s,p)
        row=l.row(align=True);row.operator('autoseamuv.force_seam');row.operator('autoseamuv.protect_seam');l.operator('autoseamuv.clear_edge_tags')
        l.prop(s,'maintain_symmetry');l.operator('autoseamuv.mark_only',icon='MOD_UVPROJECT');l.operator('autoseamuv.mark_and_unwrap',icon='PLAY')
class AUTOSEAMUV_PT_unwrap(_Sub,bpy.types.Panel):
    bl_idname='AUTOSEAMUV_PT_unwrap';bl_label='Unwrap'
    def draw(self,c):
        l=self.layout;s=c.scene.autoseamuv_settings
        for p in ('uv_map_name','create_uv_if_missing','unwrap_method','relax_after_unwrap','relax_iterations','preserve_boundary','respect_pins'):l.prop(s,p)
        l.prop(s,'straighten_circular_strip_islands')
        if s.straighten_circular_strip_islands:
            l.prop(s,'circular_strip_min_faces');l.prop(s,'circular_strip_margin')
        l.operator('autoseamuv.unwrap_only');l.separator();l.label(text='Texel Density')
        row=l.row(align=True);row.prop(s,'texture_width');row.prop(s,'texture_height');l.prop(s,'texel_unit');l.prop(s,'target_texel_density');l.prop(s,'measured_texel_density');
        row=l.row(align=True);row.operator('autoseamuv.get_texel_density');row.operator('autoseamuv.set_texel_density')
class AUTOSEAMUV_PT_pack(_Sub,bpy.types.Panel):
    bl_idname='AUTOSEAMUV_PT_pack';bl_label='Pack'
    def draw(self,c):
        l=self.layout;s=c.scene.autoseamuv_settings
        for p in ('pack_shape_method','pack_rotation','pack_margin_method','lock_pinned_islands','pack_pin_method','merge_overlapping','pack_target','margin'):l.prop(s,p)
        l.operator('autoseamuv.auto_unwrap_pack');l.operator('autoseamuv.atlas_pack_selected_objects');l.separator();l.label(text='Diagnostic Grid Layout');l.prop(s,'grid_layout_mode')
        l.prop(s,'atlas_texture_size');l.prop(s,'atlas_pixel_margin');l.prop(s,'atlas_average_island_scale');l.prop(s,'atlas_pack_rotate')
        if s.grid_layout_mode=='FIT_EACH':l.label(text='Relative Texel Density will be changed',icon='ERROR')
class AUTOSEAMUV_PT_validate(_Sub,bpy.types.Panel):
    bl_idname='AUTOSEAMUV_PT_validate';bl_label='Validate'
    def draw(self,c):
        l=self.layout;s=c.scene.autoseamuv_settings;l.prop(s,'uv_zero_tolerance');l.prop(s,'stretch_warning_threshold');l.operator('autoseamuv.validate_uv',icon='VIEWZOOM');l.operator('autoseamuv.check_uv_overlap');l.label(text=s.report_summary)
class AUTOSEAMUV_PT_utilities(_Sub,bpy.types.Panel):
    bl_idname='AUTOSEAMUV_PT_utilities';bl_label='Utilities';bl_options={'DEFAULT_CLOSED'}
    def draw(self,c):
        l=self.layout;s=c.scene.autoseamuv_settings
        row=l.row(align=True);row.operator('autoseamuv.seams_from_sharp');row.operator('autoseamuv.sharp_from_seams');row=l.row(align=True);row.operator('autoseamuv.select_seams');row.operator('autoseamuv.select_open_edges')
        l.separator();l.prop(s,'mirror_axis');l.prop(s,'mirror_tolerance');l.prop(s,'mirror_direction');l.operator('autoseamuv.mirror_seams')
        l.separator();l.prop(s,'seam_group_name');l.prop(s,'seam_group_apply_mode');row=l.row(align=True);row.operator('autoseamuv.create_seam_group');row.operator('autoseamuv.update_seam_group');row=l.row(align=True);row.operator('autoseamuv.apply_seam_group');row.operator('autoseamuv.delete_seam_group');l.operator('autoseamuv.clear_seams')
CLASSES=(AUTOSEAMUV_PT_panel,AUTOSEAMUV_PT_auto_seam,AUTOSEAMUV_PT_unwrap,AUTOSEAMUV_PT_pack,AUTOSEAMUV_PT_validate,AUTOSEAMUV_PT_utilities)
