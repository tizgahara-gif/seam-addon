"""User interface panel for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy


class AUTOSEAMUV_PT_panel(bpy.types.Panel):
    """3D View sidebar panel for automatic seam and UV operations."""

    bl_idname = "AUTOSEAMUV_PT_panel"
    bl_label = "Auto Seam UV"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Auto UV"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.autoseamuv_settings

        seam_box = layout.box()
        seam_box.label(text="Seam Detection")
        seam_box.prop(settings, "angle_threshold")
        seam_box.prop(settings, "clear_existing")
        seam_box.prop(settings, "material_boundary")
        seam_box.prop(settings, "boundary_edges")
        seam_box.prop(settings, "non_manifold_edges")
        seam_box.prop(settings, "longitudinal_seam_helper")

        uv_box = layout.box()
        uv_box.label(text="UV Settings")
        uv_box.prop(settings, "uv_map_name")
        uv_box.prop(settings, "create_uv_if_missing")
        uv_box.prop(settings, "unwrap_method")
        uv_box.prop(settings, "margin")
        uv_box.prop(settings, "average_islands")
        uv_box.prop(settings, "equal_region_pack")
        if settings.equal_region_pack:
            uv_box.prop(settings, "equal_region_margin")
            uv_box.prop(settings, "equal_region_layout")
        else:
            uv_box.prop(settings, "pack_islands")

        grid_box = layout.box()
        grid_box.label(text="Grid Settings")
        grid_box.prop(settings, "grid_fit_to_cell")
        grid_box.prop(settings, "grid_cell_margin")
        grid_box.prop(settings, "grid_cell_fill_ratio")

        post_box = layout.box()
        post_box.label(text="Post Process")
        post_box.prop(settings, "straighten_circular_strip_islands")
        if settings.straighten_circular_strip_islands:
            post_box.prop(settings, "circular_strip_min_faces")
            post_box.prop(settings, "circular_strip_margin")

        processing_box = layout.box()
        processing_box.label(text="Processing")
        processing_box.prop(settings, "process_shared_mesh_once")

        atlas_box = layout.box()
        atlas_box.label(text="Pack")
        atlas_box.prop(settings, "atlas_texture_size")
        atlas_box.prop(settings, "atlas_pixel_margin")
        atlas_box.prop(settings, "atlas_average_island_scale")
        atlas_box.prop(settings, "atlas_pack_rotate")

        validation_box = layout.box()
        validation_box.label(text="Validation")
        validation_box.prop(settings, "overlap_epsilon")
        validation_box.prop(settings, "check_overlap_across_objects")
        validation_box.prop(settings, "assign_overlap_debug_material")

        actions_box = layout.box()
        actions_box.label(text="Actions")
        actions_box.operator("autoseamuv.mark_only", text="Auto Mark Seams Only", icon="MOD_UVPROJECT")
        actions_box.operator("autoseamuv.unwrap_only", text="Auto Unwrap Grid", icon="UV")
        actions_box.operator("autoseamuv.auto_unwrap_pack", text="Auto Unwrap Pack", icon="UV")
        actions_box.operator("autoseamuv.mark_and_unwrap", text="Auto Seam + Unwrap", icon="PLAY")
        actions_box.operator("autoseamuv.atlas_pack_selected_objects", text="Atlas Pack Selected Objects", icon="UV")
        actions_box.operator("autoseamuv.check_uv_overlap", text="Check UV Overlap", icon="VIEWZOOM")
        actions_box.operator("autoseamuv.clear_uv_overlap_highlight", text="Clear UV Overlap Highlight", icon="BRUSH_DATA")
        actions_box.operator("autoseamuv.clear_seams", text="Clear Seams", icon="X")
