"""Five-stage UV-production sidebar UI for Blender 5.1."""

import bpy


def _mesh_objects(context):
    return [obj for obj in getattr(context, "selected_objects", ()) if obj.type == "MESH"]


def _active_uv(context):
    obj = getattr(context, "active_object", None)
    if obj is None or obj.type != "MESH":
        return None
    return obj.data.uv_layers.active


def _selected_face_count(context):
    obj = getattr(context, "active_object", None)
    if obj is None or obj.type != "MESH" or context.mode != "EDIT_MESH":
        return 0
    # Mesh polygon selection is sufficient for status display and avoids changing
    # edit-mesh state merely by drawing the panel.
    return sum(poly.select for poly in obj.data.polygons)


def _warning(layout, text):
    row = layout.row()
    row.alert = True
    row.label(text=text, icon="ERROR")


class AUTOSEAMUV_PT_panel(bpy.types.Panel):
    bl_idname = "AUTOSEAMUV_PT_panel"
    bl_label = "Auto Seam UV Equalizer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Auto UV"

    def draw(self, context):
        layout, settings = self.layout, context.scene.autoseamuv_settings
        meshes = _mesh_objects(context)
        active_uv = _active_uv(context)
        edit_mode = context.mode == "EDIT_MESH"

        status = layout.box()
        status.label(text="Status", icon="INFO")
        status.label(text=f"Active UV: {active_uv.name if active_uv else 'None'}")
        status.label(text=f"Mode: {'Edit' if edit_mode else 'Object'}")
        if edit_mode:
            status.label(text=f"Selected Faces: {_selected_face_count(context)}")
        status.label(text=f"Selected Objects: {len(meshes)}")
        if active_uv is None:
            _warning(status, "No active UV map.")

        self._draw_seam(layout, settings)
        self._draw_unwrap(layout, settings, edit_mode)
        self._draw_layout(layout, settings, meshes, active_uv, edit_mode)
        self._draw_symmetry(layout, settings, active_uv, edit_mode)
        self._draw_validation(layout, settings)

    @staticmethod
    def _draw_seam(layout, settings):
        box = layout.box()
        box.label(text="1. Seam", icon="MOD_UVPROJECT")
        box.prop(settings, "seam_mode", text="Mode")
        box.label(text="Scope: Selected Objects")
        if settings.seam_mode == "CLASSIC":
            classic = box.column(align=True)
            classic.prop(settings, "angle_threshold")
            classic.prop(settings, "material_boundary")
            classic.prop(settings, "boundary_edges")
            classic.prop(settings, "non_manifold_edges")
            classic.operator("autoseamuv.mark_only", text="Generate Seams", icon="MOD_UVPROJECT")
        else:
            box.prop(settings, "seam_preset", text="Preset")
            descriptions = {
                "ORGANIC": "Fewer seams, garment structure and UV quality prioritized.",
                "HARD_SURFACE": "Sharp angles, material boundaries and hard edges prioritized.",
                "CYLINDER": "Topology-flow longitudinal seams prioritized.",
                "MANUAL": "Force / Protect / existing seams prioritized.",
            }
            box.label(text=descriptions[settings.seam_preset], icon="INFO")
            row = box.row(align=True)
            row.operator("autoseamuv.analyze_seams", text="Analyze Seams", icon="VIEWZOOM")
            row.operator("autoseamuv.generate_seams", text="Generate Seams", icon="MOD_UVPROJECT")

        assist = box.column(align=True)
        assist.label(text="Assist")
        row = assist.row(align=True)
        boundary = row.operator("autoseamuv.mark_selected_region_boundary", text="Selected Boundary", icon="EDGESEL")
        boundary.include_open_boundaries = settings.include_open_boundaries
        row.operator("autoseamuv.mirror_seams", text="Mirror Seam")
        mirror = assist.row(align=True)
        mirror.prop(settings, "mirror_axis", text="Axis")
        mirror.prop(settings, "mirror_direction", text="Direction")
        if settings.seam_mode != "CLASSIC":
            row = assist.row(align=True)
            row.operator("autoseamuv.force_seam", text="Force")
            row.operator("autoseamuv.protect_seam", text="Protect")
            row.operator("autoseamuv.clear_edge_tags", text="Clear Tags")
            box.prop(settings, "use_professional_garment_prior", text="Professional Garment Prior")

        box.prop(settings, "show_seam_advanced", toggle=True)
        if settings.show_seam_advanced:
            advanced = box.column(align=True)
            if settings.seam_mode == "CLASSIC":
                advanced.prop(settings, "clear_existing")
                advanced.prop(settings, "longitudinal_seam_helper")
            else:
                advanced.prop(settings, "max_chart_distortion")
                advanced.prop(settings, "seam_count_penalty")
                advanced.prop(settings, "seam_minimum_spacing")
                advanced.prop(settings, "straightness_bias")
                advanced.prop(settings, "chart_refinement_iterations")
                advanced.prop(settings, "preserve_existing_seams")
                advanced.prop(settings, "character_front_axis")

    @staticmethod
    def _draw_unwrap(layout, settings, edit_mode):
        box = layout.box()
        box.label(text="2. Unwrap", icon="UV")
        box.prop(settings, "unwrap_method", text="Method")
        box.label(text="Scope")
        selected = box.column()
        selected.enabled = edit_mode
        selected.operator("autoseamuv.unwrap_selected_faces", text="Unwrap Selected Faces", icon="FACESEL")
        if not edit_mode:
            _warning(box, "Selected Faces requires Edit Mode.")
        box.operator("autoseamuv.unwrap_only", text="Unwrap Selected Objects", icon="UV")

        box.prop(settings, "show_ring_strip", toggle=True)
        if settings.show_ring_strip:
            ring = box.column(align=True)
            ring.prop(settings, "ring_seam_mode", text="Seam")
            ring.prop(settings, "ring_layout", text="Layout")
            ring.prop(settings, "ring_spacing", text="Spacing")
            ring.prop(settings, "ring_orientation", text="Orientation")
            ring.prop(settings, "ring_normalize", text="Normalize")
            row = ring.row(align=True)
            row.operator("autoseamuv.detect_ring_strip", text="Detect Ring / Strip")
            row.operator("autoseamuv.unwrap_ring_strip", text="Unwrap Ring / Strip")

    @staticmethod
    def _draw_layout(layout, settings, meshes, active_uv, edit_mode):
        box = layout.box()
        box.label(text="3. Layout", icon="UV")
        weighted = box.column(align=True)
        weighted.label(text="Weighted Island Layout")
        weighted.prop(settings, "weighted_scope", text="Scope")
        weighted.prop(settings, "weighted_target_region", text="Target UV Region")
        weighted.prop(settings, "weighted_density_influence", text="Density Influence")
        weighted.prop(settings, "weighted_scale_mode", text="Scale Mode")
        weighted.prop(settings, "weighted_texture_size", text="Texture Size")
        weighted.prop(settings, "weighted_padding_pixels", text="Padding Pixels")
        if settings.weighted_scope == "SELECTED_FACES" and not edit_mode:
            _warning(weighted, "Selected Faces requires Edit Mode.")
        action = weighted.row()
        action.enabled = active_uv is not None and not (
            settings.weighted_scope == "SELECTED_FACES" and not edit_mode)
        action.operator("autoseamuv.weighted_island_layout", text="Weighted Island Layout")

        pack = box.column(align=True)
        pack.separator()
        pack.label(text="Pack Islands")
        pack.prop(settings, "margin", text="UV Margin")
        pack.prop(settings, "pack_rotation", text="Rotation")
        pack.prop(settings, "pack_margin_method", text="Margin Method")
        action = pack.row()
        action.enabled = active_uv is not None
        action.operator("autoseamuv.pack_islands", text="Pack Islands")
        if len(meshes) > 1:
            _warning(pack, "Objects will be packed independently.")
            pack.label(text="Use Atlas Pack for a shared texture atlas.", icon="INFO")

        atlas = box.column(align=True)
        atlas.separator()
        atlas.label(text="Multiple Objects")
        atlas.operator("autoseamuv.atlas_pack_selected_objects", text="Atlas Pack Selected Objects")

    @staticmethod
    def _draw_symmetry(layout, settings, active_uv, edit_mode):
        box = layout.box()
        box.label(text="4. Symmetry")
        mesh = box.column(align=True)
        mesh.label(text="Mesh Symmetry")
        mesh.prop(settings, "symmetry_axis", text="Axis")
        mesh.prop(settings, "symmetry_direction", text="Mesh Source Side")
        mesh.prop(settings, "symmetry_scope", text="Scope")
        mesh.prop(settings, "symmetry_tolerance", text="Tolerance")
        if settings.symmetry_scope == "SELECTED" and not edit_mode:
            _warning(mesh, "Selected Faces requires Edit Mode.")
        mesh.operator("autoseamuv.validate_symmetry", text="Validate Symmetry")

        standard = box.column(align=True)
        standard.separator()
        standard.label(text="Standard UV Transfer")
        standard.prop(settings, "symmetry_layout", text="Layout")
        if settings.symmetry_layout == "SEPARATE_MIRRORED":
            standard.prop(settings, "symmetry_island_gap", text="Island Gap")
        action = standard.row()
        action.enabled = active_uv is not None
        action.operator("autoseamuv.transfer_symmetric_uv", text="Transfer Symmetric UV")

        exact = box.column(align=True)
        exact.separator()
        exact.label(text="Exact Texture-X")
        exact.prop(settings, "texture_source_side", text="Texture Source Side")
        target = settings.weighted_target_region
        source = settings.texture_source_side
        if target == "FULL":
            exact.label(text="Exact Texture-X requires source UVs inside one texture half.", icon="INFO")
        elif target != source:
            _warning(exact, "Target region does not match Exact Texture-X source.")
        else:
            exact.label(text="Ready for Exact Texture-X", icon="CHECKMARK")
        action = exact.row()
        action.enabled = active_uv is not None
        action.operator("autoseamuv.transfer_exact_texture_x_symmetry", text="Exact Texture-X Symmetry")

    @staticmethod
    def _draw_validation(layout, settings):
        box = layout.box()
        box.label(text="5. Validation", icon="CHECKMARK")
        overlap = box.column(align=True)
        overlap.label(text="UV Overlap")
        overlap.operator("autoseamuv.check_uv_overlap", text="Check Overlap")
        overlap.operator("autoseamuv.clear_uv_overlap_highlight", text="Clear Overlap Selection")
        stretch = box.column(align=True)
        stretch.separator()
        stretch.label(text="Stretch")
        stretch.operator("autoseamuv.validate_uv", text="Check Stretch")
        stretch.label(text="Last Stretch Report")
        stretch.label(text=settings.report_summary, icon="INFO")


CLASSES = (AUTOSEAMUV_PT_panel,)
