"""Five-stage UV-production sidebar UI for Blender 5.1."""

import bpy
from .translations import iface_
from .operators import resolve_atlas_targets, resolve_layout_targets


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


def _warning(layout, text, *values):
    row = layout.row()
    row.alert = True
    row.label(text=iface_(text, *values), icon="ERROR")


def _info(layout, text):
    layout.label(text=iface_(text), icon="INFO")


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
        status.label(text=iface_("Active UV: %s") % (active_uv.name if active_uv else iface_("None")))
        status.label(text=iface_("Mode: %s") % iface_("Edit" if edit_mode else "Object"))
        if edit_mode:
            status.label(text=iface_("Selected Faces: %d") % _selected_face_count(context))
        status.label(text=iface_("Selected Objects: %d") % len(meshes))
        if active_uv is None:
            if settings.create_uv_if_missing:
                _info(status, "No active UV map. A UV map will be created when Unwrap runs.")
            else:
                _warning(status, "No active UV map. Enable Create UV If Missing or create a UV map manually.")

        processing = layout.box()
        processing.label(text="Processing")
        if len(meshes) > 1:
            processing.label(text=iface_("Selected Mesh Objects: %d") % len(meshes))
            processing.label(text=iface_("Unique Mesh Data: %d") %
                             len({obj.data.as_pointer() for obj in meshes}))
        processing.prop(settings, "process_shared_mesh_once", text="Process Shared Mesh Data Once")

        self._draw_seam(layout, settings, context, edit_mode)
        self._draw_unwrap(layout, settings, edit_mode)
        self._draw_layout(layout, settings, meshes, active_uv, edit_mode, context)
        self._draw_symmetry(layout, settings, active_uv, edit_mode)
        self._draw_validation(layout, settings)

    @staticmethod
    def _draw_seam(layout, settings, context, edit_mode):
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
            box.label(text=iface_(descriptions[settings.seam_preset]), icon="INFO")
            row = box.row(align=True)
            row.operator("autoseamuv.analyze_seams", text="Analyze Seams", icon="VIEWZOOM")
            row.operator("autoseamuv.generate_seams", text="Generate Seams", icon="MOD_UVPROJECT")

        assist = box.column(align=True)
        assist.label(text="Assist — Active Object")
        assist.prop(settings, "include_open_boundaries", text="Include Open Boundaries")
        row = assist.row(align=True)
        boundary = row.operator("autoseamuv.mark_selected_region_boundary", text="Selected Boundary", icon="EDGESEL")
        boundary.include_open_boundaries = settings.include_open_boundaries
        mirror_action = row.row()
        mirror_action.enabled = not (settings.mirror_direction == "SELECTED" and not edit_mode)
        mirror_action.operator("autoseamuv.mirror_seams", text="Mirror Seam State")
        mirror = assist.row(align=True)
        mirror.prop(settings, "mesh_symmetry_axis", text="Mesh Symmetry Axis")
        mirror.prop(settings, "mesh_symmetry_tolerance", text="Tolerance")
        mirror.prop(settings, "mirror_direction", text="Direction")
        if settings.mirror_direction == "SELECTED" and not edit_mode:
            _warning(assist, "Selected Side mirroring requires Edit Mode with selected edges.")
        if settings.seam_mode != "CLASSIC":
            assist.label(text="Selected Edges")
            row = assist.row(align=True)
            row.enabled = edit_mode
            row.operator("autoseamuv.force_seam", text="Force")
            row.operator("autoseamuv.protect_seam", text="Protect")
            if not edit_mode:
                _warning(assist, "Force / Protect requires Edit Mode and selected edges.")
            assist.label(text="Active Object")
            assist.operator("autoseamuv.clear_edge_tags", text="Clear All Tags")
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
                advanced.prop(settings, "use_distortion_guided_candidates")
                advanced.prop(settings, "use_edge_loop_completion")

    @staticmethod
    def _draw_unwrap(layout, settings, edit_mode):
        box = layout.box()
        box.label(text="2. Unwrap", icon="UV")
        box.prop(settings, "unwrap_method", text="Method")
        box.prop(settings, "unwrap_margin", text="Unwrap Margin")
        box.label(text="Scope")
        selected = box.column()
        selected.enabled = edit_mode
        selected.operator("autoseamuv.unwrap_selected_faces", text="Unwrap Selected Faces", icon="FACESEL")
        if not edit_mode:
            _warning(box, "Selected Faces requires Edit Mode.")
        box.operator("autoseamuv.unwrap_only", text="Unwrap Selected Objects", icon="UV")

        box.prop(settings, "show_unwrap_advanced", toggle=True)
        if settings.show_unwrap_advanced:
            post = box.column(align=True)
            post.label(text="Selected Objects Post-Unwrap")
            post.prop(settings, "average_islands", text="Average Island Scale")
            post.prop(settings, "straighten_circular_strip_islands", text="Straighten Circular Strip Islands")

        box.prop(settings, "show_ring_strip", toggle=True)
        if settings.show_ring_strip:
            ring = box.column(align=True)
            ring.label(text=("Scope: Active Object / Selected Faces" if edit_mode else
                             "Scope: Selected Mesh Objects / Whole Objects"), icon="INFO")
            ring.prop(settings, "ring_seam_mode", text="Seam")
            ring.prop(settings, "ring_layout", text="Layout")
            ring.prop(settings, "ring_spacing", text="Spacing")
            ring.prop(settings, "ring_orientation", text="Orientation")
            ring.prop(settings, "ring_normalize", text="Normalize")
            row = ring.row(align=True)
            row.operator("autoseamuv.detect_ring_strip", text="Detect Ring / Strip")
            row.operator("autoseamuv.unwrap_ring_strip", text="Unwrap Ring / Strip")

    @staticmethod
    def _draw_layout(layout, settings, meshes, active_uv, edit_mode, context):
        box = layout.box()
        box.label(text="3. Layout", icon="UV")
        preflight = resolve_layout_targets(context)
        if len(meshes) > 1 or preflight["missing_uv_count"]:
            box.label(text=iface_("Selected Mesh Objects: %d") % preflight["target_count"])
            box.label(text=iface_("UV Ready: %d / %d") %
                      (preflight["valid_uv_count"], preflight["target_count"]))
        if preflight["missing_uv_count"]:
            _warning(box, "%d selected mesh object(s) have no usable UV map.",
                     preflight["missing_uv_count"])
        weighted = box.column(align=True)
        weighted.label(text="Weighted Island Layout")
        weighted.prop(settings, "weighted_scope", text="Scope")
        weighted.prop(settings, "weighted_target_region", text="Target UV Region")
        weighted.prop(settings, "weighted_density_influence", text="Density Influence")
        weighted.prop(settings, "weighted_scale_mode", text="Scale Mode")
        weighted.prop(settings, "weighted_texture_size", text="Texture Size")
        weighted.prop(settings, "weighted_padding_pixels", text="Padding Pixels")
        if settings.weighted_scope == "SELECTED_FACES" and not edit_mode:
            _warning(weighted, "Selected UV Islands requires Edit Mode.")
        action = weighted.row()
        action.enabled = preflight["all_ready"] and not (
            settings.weighted_scope == "SELECTED_FACES" and not edit_mode)
        action.operator("autoseamuv.weighted_island_layout", text="Weighted Island Layout")
        weighted.label(text="Each object is laid out independently.", icon="INFO")
        weighted.separator()
        weighted.label(text="Shared Atlas")
        shared = weighted.row()
        shared.enabled = (preflight["all_ready"] and preflight["unique_mesh_count"] >= 2 and
                          not (settings.weighted_scope == "SELECTED_FACES" and not edit_mode))
        shared.operator("autoseamuv.shared_weighted_atlas", text="Shared Weighted Atlas")
        weighted.label(text="All selected objects share one weighted atlas.", icon="INFO")
        weighted.label(text="Shared Weighted Atlas reallocates UV area globally.", icon="INFO")
        weighted.label(text="Atlas Pack preserves existing island scaling unless its options change it.", icon="INFO")

        pack = box.column(align=True)
        pack.separator()
        pack.label(text="Pack Islands")
        if settings.weighted_target_region in {"LEFT_HALF", "RIGHT_HALF"}:
            _warning(pack, "Half-region layout is active. Packing may break the Exact Texture-X workflow.")
        pack.prop(settings, "pack_margin", text="Pack Margin")
        pack.prop(settings, "pack_rotation", text="Rotation")
        pack.prop(settings, "pack_margin_method", text="Margin Method")
        pack.prop(settings, "show_pack_advanced", toggle=True)
        if settings.show_pack_advanced:
            advanced = pack.column(align=True)
            advanced.prop(settings, "pack_shape_method", text="Shape Method")
            advanced.prop(settings, "lock_pinned_islands", text="Lock Pinned Islands")
            if settings.lock_pinned_islands:
                advanced.prop(settings, "pack_pin_method", text="Pin Method")
            advanced.prop(settings, "merge_overlapping", text="Merge Overlapping")
            advanced.prop(settings, "pack_target", text="Pack Target")
        action = pack.row()
        action.enabled = preflight["all_ready"]
        action.operator("autoseamuv.pack_islands", text="Pack Islands")
        if len(meshes) > 1:
            _warning(pack, "Objects will be packed independently.")
            pack.label(text="Use Atlas Pack for a shared texture atlas.", icon="INFO")

        atlas = box.column(align=True)
        atlas.separator()
        atlas.label(text="Multiple Objects")
        if settings.weighted_target_region in {"LEFT_HALF", "RIGHT_HALF"}:
            _warning(atlas, "Half-region layout is active. Packing may break the Exact Texture-X workflow.")
        atlas.prop(settings, "show_atlas_settings", toggle=True)
        if settings.show_atlas_settings:
            atlas_settings = atlas.column(align=True)
            atlas_settings.prop(settings, "atlas_uv_source", text="UV Source")
            atlas_settings.prop(settings, "atlas_texture_size", text="Texture Size")
            atlas_settings.prop(settings, "atlas_pixel_margin", text="Pixel Margin")
            atlas_settings.prop(settings, "atlas_average_island_scale", text="Average Island Scale")
            if (settings.weighted_scale_mode == "ALLOCATE_BY_IMPORTANCE" and
                    settings.atlas_average_island_scale):
                _warning(atlas_settings, "Average Island Scale may override the relative scaling created by Weighted Island Layout.")
            atlas_settings.prop(settings, "atlas_pack_rotate", text="Allow Rotation")
        atlas_preflight = resolve_atlas_targets(context, settings)
        action = atlas.row()
        action.enabled = atlas_preflight["all_ready"]
        action.operator("autoseamuv.atlas_pack_selected_objects", text="Atlas Pack Selected Objects")

    @staticmethod
    def _draw_symmetry(layout, settings, active_uv, edit_mode):
        box = layout.box()
        box.label(text="4. Symmetry")
        mesh = box.column(align=True)
        mesh.label(text="Mesh Symmetry")
        mesh.label(text="Target: Active Object", icon="INFO")
        mesh.prop(settings, "mesh_symmetry_axis", text="Mesh Symmetry Axis")
        mesh.prop(settings, "symmetry_direction", text="Mesh Source Side")
        mesh.prop(settings, "symmetry_scope", text="Faces")
        mesh.prop(settings, "mesh_symmetry_tolerance", text="Mesh Symmetry Tolerance")
        if settings.symmetry_scope == "SELECTED" and not edit_mode:
            _warning(mesh, "Selected Faces requires Edit Mode.")
        symmetry_available = not (settings.symmetry_scope == "SELECTED" and not edit_mode)
        action = mesh.row()
        action.enabled = symmetry_available
        action.operator("autoseamuv.validate_symmetry", text="Validate Symmetry")

        standard = box.column(align=True)
        standard.separator()
        standard.label(text="Standard UV Transfer")
        standard.prop(settings, "symmetry_layout", text="Layout")
        if settings.symmetry_layout == "SEPARATE_MIRRORED":
            standard.prop(settings, "symmetry_island_gap", text="Island Gap")
        action = standard.row()
        action.enabled = active_uv is not None and symmetry_available
        action.operator("autoseamuv.transfer_symmetric_uv", text="Transfer Symmetric UV")

        island_sync = box.column(align=True)
        island_sync.separator()
        island_sync.label(text="Island Synchronization")
        island_sync.label(text="Source: Selected UV Island")
        island_sync.label(text="Mode: Copy Exact")
        island_sync.label(text="Synchronize Seams", icon="CHECKMARK")
        island_sync.label(text=(
            "Copies the selected island's UV coordinates and seam ON/OFF state "
            "to its mesh-symmetric counterpart."), icon="INFO")
        island_sync.label(text="The UV islands will overlap exactly.", icon="INFO")
        action = island_sync.row()
        action.enabled = edit_mode and active_uv is not None
        action.operator("autoseamuv.sync_mirrored_uv_island",
                        text="Synchronize Mirrored UV Island")

        transform = box.column(align=True)
        transform.separator()
        transform.label(text="Island Transform")
        transform.label(text="Target: Active Object")
        transform.label(text="Scope: Selected UV Islands")
        action = transform.row()
        action.enabled = edit_mode and active_uv is not None
        action.operator("autoseamuv.flip_selected_uv_islands",
                        text="Flip Selected UV Islands")

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
            exact.label(text="Layout settings match Exact Texture-X.", icon="CHECKMARK")
        action = exact.row()
        action.enabled = active_uv is not None and symmetry_available
        action.operator("autoseamuv.transfer_exact_texture_x_symmetry", text="Exact Texture-X Symmetry")

    @staticmethod
    def _draw_validation(layout, settings):
        box = layout.box()
        box.label(text="5. Validation", icon="CHECKMARK")
        overlap = box.column(align=True)
        overlap.label(text="UV Overlap")
        overlap.label(text="Scope: Selected Objects")
        overlap.prop(settings, "check_overlap_across_objects", text="Check Across Objects")
        overlap.operator("autoseamuv.check_uv_overlap", text="Check Overlap")
        overlap.operator("autoseamuv.clear_uv_overlap_highlight", text="Clear Overlap Selection")
        quality = box.column(align=True)
        quality.separator()
        quality.label(text="UV Quality")
        quality.operator("autoseamuv.validate_uv", text="Run UV Quality Check")
        quality.label(text="Problem faces may be selected in Edit Mode.", icon="INFO")
        quality.label(text="Last Quality Report")
        quality.label(text=settings.report_summary, icon="INFO")


CLASSES = (AUTOSEAMUV_PT_panel,)
