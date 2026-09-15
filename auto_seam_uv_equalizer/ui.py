"""UV-production-stage sidebar UI for Blender 5.1."""

import bpy


class AUTOSEAMUV_PT_panel(bpy.types.Panel):
    bl_idname = "AUTOSEAMUV_PT_panel"
    bl_label = "Auto Seam UV"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Auto UV"

    def draw(self, context):
        layout, settings = self.layout, context.scene.autoseamuv_settings

        seam_box = layout.box()
        seam_box.label(text="1. Seam", icon="MOD_UVPROJECT")
        seam_box.prop(settings, "seam_mode")
        if settings.seam_mode == "CLASSIC":
            seam_box.prop(settings, "angle_threshold")
            seam_box.prop(settings, "material_boundary")
            seam_box.prop(settings, "boundary_edges")
            seam_box.prop(settings, "non_manifold_edges")
            seam_box.operator("autoseamuv.mark_only", text="Generate Seams")
        else:
            seam_box.prop(settings, "seam_preset", text="Preset")
            row = seam_box.row(align=True)
            row.operator("autoseamuv.analyze_seams", text="Analyze Seams", icon="VIEWZOOM")
            row.operator("autoseamuv.generate_seams", text="Generate Seams", icon="MOD_UVPROJECT")
            seam_box.prop(settings, "preserve_existing_seams")
            seam_box.prop(settings, "show_seam_advanced", toggle=True)
            if settings.show_seam_advanced:
                advanced = seam_box.column(align=True)
                advanced.prop(settings, "max_chart_distortion")
                advanced.prop(settings, "seam_count_penalty")
                advanced.prop(settings, "curvature_bias")
                advanced.prop(settings, "weight_material")
                advanced.prop(settings, "straightness_bias")
                advanced.prop(settings, "seam_minimum_spacing")
                advanced.prop(settings, "chart_refinement_iterations")
        assist = seam_box.column(align=True)
        assist.label(text="Assist")
        boundary = assist.operator("autoseamuv.mark_selected_region_boundary", text="Selected Boundary", icon="EDGESEL")
        boundary.include_open_boundaries = settings.include_open_boundaries
        row = assist.row(align=True)
        row.operator("autoseamuv.force_seam", text="Force")
        row.operator("autoseamuv.protect_seam", text="Protect")
        assist.operator("autoseamuv.mirror_seams", text="Mirror Seam")

        unwrap = layout.box()
        unwrap.label(text="2. Unwrap", icon="UV")
        unwrap.prop(settings, "unwrap_method", text="Method")
        unwrap.prop(settings, "uv_map_name")
        unwrap.operator("autoseamuv.unwrap_selected_faces", text="Unwrap Selected Faces", icon="FACESEL")
        unwrap.operator("autoseamuv.unwrap_only", text="Unwrap Whole Object", icon="UV")
        ring = unwrap.column(align=True)
        ring.label(text="Ring / Strip")
        ring.prop(settings, "ring_seam_mode")
        row = ring.row(align=True)
        row.operator("autoseamuv.detect_ring_strip", text="Detect")
        row.operator("autoseamuv.unwrap_ring_strip", text="Unwrap")

        layout_box = layout.box()
        layout_box.label(text="3. Layout", icon="UV")
        layout_box.prop(settings, "weighted_target_region", text="Target UV Region")
        layout_box.operator("autoseamuv.weighted_island_layout", text="Weighted Island Layout")
        layout_box.prop(settings, "margin")
        layout_box.operator("autoseamuv.pack_islands", text="Pack Islands")

        symmetry = layout.box()
        symmetry.label(text="4. Symmetry")
        symmetry.operator("autoseamuv.validate_symmetry", text="Validate Symmetry")
        symmetry.operator("autoseamuv.transfer_symmetric_uv", text="Transfer Symmetric UV")
        symmetry.prop(settings, "texture_source_side", text="Texture Source")
        symmetry.operator("autoseamuv.transfer_exact_texture_x_symmetry", text="Exact Texture-X Symmetry")

        validation = layout.box()
        validation.label(text="5. Validation", icon="CHECKMARK")
        validation.label(text=settings.report_summary, icon="INFO")
        validation.operator("autoseamuv.check_uv_overlap", text="Check Overlap")
        validation.operator("autoseamuv.validate_uv", text="Check Stretch")


CLASSES = (AUTOSEAMUV_PT_panel,)
