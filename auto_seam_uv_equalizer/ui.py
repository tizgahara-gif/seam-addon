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

        processing_box = layout.box()
        processing_box.label(text="Processing")
        processing_box.prop(settings, "process_shared_mesh_once")

        arrange_box = layout.box()
        arrange_box.label(text="Selected UV Arrange")
        arrange_box.prop(settings, "arrange_selected_grid_margin")
        arrange_box.prop(settings, "arrange_selected_grid_layout")
        arrange_box.prop(settings, "duplicate_uv_before_arrange")
        arrange_box.operator(
            "autoseamuv.arrange_selected_uv_islands_to_grid",
            text="Arrange Selected UV Islands to Grid",
            icon="UV",
        )

        actions_box = layout.box()
        actions_box.label(text="Actions")
        actions_box.operator("autoseamuv.mark_only", text="Auto Mark Seams Only", icon="MOD_UVPROJECT")
        actions_box.operator("autoseamuv.unwrap_only", text="Auto Unwrap Only", icon="UV")
        actions_box.operator("autoseamuv.mark_and_unwrap", text="Auto Seam + Unwrap", icon="PLAY")
        actions_box.operator("autoseamuv.clear_seams", text="Clear Seams", icon="X")
