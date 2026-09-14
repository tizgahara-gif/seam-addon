"""Task-oriented Blender 5.1 sidebar UI."""
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

        ring_box = layout.box()
        ring_box.label(text="Ring / Strip Unwrap")
        ring_box.label(text="Topology:")
        ring_box.prop(settings, "ring_auto_detect")
        ring_box.prop(settings, "ring_layout")
        ring_box.prop(settings, "ring_spacing")
        ring_box.prop(settings, "ring_seam_mode")
        ring_box.prop(settings, "ring_orientation")
        ring_box.label(text="Options:")
        ring_box.prop(settings, "ring_normalize")
        row = ring_box.row(align=True)
        row.operator("autoseamuv.detect_ring_strip", text="Detect Ring / Strip", icon="VIEWZOOM")
        row.operator("autoseamuv.unwrap_ring_strip", text="Unwrap Ring / Strip", icon="UV")

        symmetry_box = layout.box()
        symmetry_box.label(text="Symmetric UV")
        symmetry_box.prop(settings, "symmetry_axis")
        symmetry_box.prop(settings, "symmetry_direction")
        symmetry_box.prop(settings, "symmetry_scope")
        symmetry_box.prop(settings, "symmetry_layout")
        symmetry_box.prop(settings, "symmetry_tolerance")
        if settings.symmetry_layout == "SEPARATE_MIRRORED":
            symmetry_box.prop(settings, "symmetry_island_gap")
        symmetry_box.operator("autoseamuv.validate_symmetry", text="Validate Symmetry", icon="CHECKMARK")
        symmetry_box.operator("autoseamuv.transfer_symmetric_uv", text="Transfer Symmetric UV", icon="UV")

        processing_box = layout.box()
        processing_box.label(text="Processing")
        processing_box.prop(settings, "process_shared_mesh_once")

        atlas_box = layout.box()
        atlas_box.label(text="Atlas Pack")
        atlas_box.prop(settings, "atlas_uv_source")
        if settings.atlas_uv_source == "NAMED":
            atlas_box.prop(settings, "uv_map_name")
            atlas_box.prop(settings, "create_uv_if_missing")
        atlas_box.prop(settings, "atlas_texture_size")
        atlas_box.prop(settings, "atlas_pixel_margin")
        atlas_box.prop(settings, "atlas_average_island_scale")
        atlas_box.prop(settings, "atlas_pack_rotate")

        validation_box = layout.box()
        validation_box.label(text="Validation")
        validation_box.prop(settings, "overlap_area_epsilon")
        validation_box.prop(settings, "overlap_coord_epsilon")
        validation_box.prop(settings, "check_overlap_across_objects")

        actions_box = layout.box()
        actions_box.label(text="Actions")
        actions_box.prop(settings, "include_open_boundaries")
        boundary_operator = actions_box.operator(
            "autoseamuv.mark_selected_region_boundary",
            text="Mark Selected Region Boundary as Seam",
            icon="EDGESEL",
        )
        boundary_operator.include_open_boundaries = settings.include_open_boundaries
        actions_box.operator("autoseamuv.mark_only", text="Auto Mark Seams Only", icon="MOD_UVPROJECT")
        actions_box.operator("autoseamuv.unwrap_only", text="Auto Unwrap Grid", icon="UV")
        actions_box.operator("autoseamuv.auto_unwrap_pack", text="Auto Unwrap Pack", icon="UV")
        actions_box.operator("autoseamuv.mark_and_unwrap", text="Auto Seam + Unwrap", icon="PLAY")
        actions_box.operator("autoseamuv.atlas_pack_selected_objects", text="Atlas Pack Selected Objects", icon="UV")
        actions_box.operator("autoseamuv.check_uv_overlap", text="Check UV Overlap", icon="VIEWZOOM")
        actions_box.operator("autoseamuv.clear_uv_overlap_highlight", text="Clear UV Overlap Highlight", icon="BRUSH_DATA")
        actions_box.operator("autoseamuv.clear_seams", text="Clear Seams", icon="X")
