"""Five-stage UV-production sidebar UI for Blender 5.1."""

import bpy
import bmesh
from .translations import iface_
from .operators import (resolve_atlas_targets, resolve_layout_targets,
                        selected_face_seeds_by_mesh)
from .uv_protection import has_active_uv_protection
from .simple_workflow import resolve_simple_targets


def _mesh_objects(context):
    return resolve_layout_targets(context, require_uv=False)["objects"]


def _active_uv(context):
    obj = getattr(context, "active_object", None)
    if obj is None or obj.type != "MESH":
        return None
    return obj.data.uv_layers.active


def _selected_face_count(context):
    obj = getattr(context, "active_object", None)
    if obj is None or obj.type != "MESH" or context.mode != "EDIT_MESH":
        return 0
    bm = bmesh.from_edit_mesh(obj.data)
    return sum(face.select for face in bm.faces)


def _selected_edge_count(context):
    obj = getattr(context, "active_object", None)
    if obj is None or obj.type != "MESH" or context.mode != "EDIT_MESH":
        return 0
    return sum(edge.select for edge in bmesh.from_edit_mesh(obj.data).edges)


def _warning(layout, text, *values):
    row = layout.row()
    row.alert = True
    row.label(text=iface_(text, *values), icon="ERROR")


def _error(layout, text, *values):
    """Draw an unconditional blocking/error state."""
    row = layout.row()
    row.alert = True
    row.label(text=iface_(text, *values), icon="CANCEL")


def _helper_comment(layout, settings, text, icon="INFO"):
    """Draw optional explanatory copy, never safety or state information."""
    if settings.show_helper_comments:
        layout.label(text=iface_(text), icon=icon)


def _stage_header(box, settings, property_name, text):
    """Draw a standard disclosure header and return its independent state."""
    expanded = getattr(settings, property_name)
    box.prop(
        settings,
        property_name,
        text=text,
        icon="TRIA_DOWN" if expanded else "TRIA_RIGHT",
        emboss=False,
    )
    return expanded


class AUTOSEAMUV_PT_panel(bpy.types.Panel):
    bl_idname = "AUTOSEAMUV_PT_panel"
    bl_label = "Auto Seam UV Equalizer"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Auto UV"

    def draw(self, context):
        layout, settings = self.layout, context.scene.autoseamuv_settings
        layout.prop(settings, "ui_mode", text="Mode", expand=True)
        if settings.ui_mode == "SIMPLE":
            self._draw_simple(layout, settings, context)
            return
        meshes = _mesh_objects(context)
        active_uv = _active_uv(context)
        edit_mode = context.mode == "EDIT_MESH"
        selected_faces = _selected_face_count(context)
        selected_edges = _selected_edge_count(context)

        status = layout.box()
        status.label(text="Processing", icon="INFO")
        status.label(text="Target: Selected Objects")
        status.label(text=iface_("Active UV: %s") % (active_uv.name if active_uv else iface_("None")))
        status.label(text=iface_("Selected Objects: %d") % len(meshes))
        status.label(text=iface_("Unique Mesh Data: %d") %
                     len({obj.data.as_pointer() for obj in meshes}))
        if active_uv is None:
            _error(status, "No active UV map.")
            _helper_comment(status, settings, "Selected Objects unwrap can create the configured UV map.")
            _helper_comment(status, settings, "Selected UV Islands requires an existing active UV map.")

        status.prop(settings, "show_helper_comments")

        status.prop(settings, "show_processing_options", toggle=True)
        if settings.show_processing_options:
            status.prop(settings, "process_shared_mesh_once",
                        text="Process Shared Mesh Data Once")

        self._draw_seam(layout, settings, context, edit_mode, selected_faces, selected_edges)
        self._draw_unwrap(layout, settings, edit_mode, active_uv, context)
        self._draw_layout(layout, settings, meshes, active_uv, edit_mode, context)
        self._draw_symmetry(layout, settings, active_uv, edit_mode, selected_faces)
        self._draw_validation(layout, settings)

    @staticmethod
    def _draw_simple(layout, settings, context):
        targets = resolve_simple_targets(context)
        box = layout.box()
        box.label(text="Processing", icon="INFO")
        box.label(text="Target: Selected Mesh Objects")
        box.label(text=iface_("Selected Mesh Objects: %d") % targets.selected_count)
        box.label(text=iface_("Unique Mesh Data: %d") % targets.unique_mesh_count)
        box.label(text=iface_("UV Ready: %d / %d") %
                  (targets.uv_ready_count, targets.unique_mesh_count))
        if targets.empty_mesh_count:
            _warning(box, "%d empty mesh objects will be skipped.",
                     targets.empty_mesh_count)
        if not targets.editable_count:
            _error(box, "No editable mesh targets.")
        box.prop(settings, "show_helper_comments")
        if context.mode == "EDIT_MESH":
            _helper_comment(box, settings,
                            "Simple stages process whole selected mesh targets.")
            _helper_comment(box, settings,
                            "Component selection does not limit the scope.")

        seam = layout.box()
        seam.label(text="1. Seam")
        action = seam.column(align=True)
        action.enabled = targets.editable_count > 0
        action.operator("autoseamuv.simple_auto_seam", text="Auto Seam", icon="MOD_UVPROJECT")
        _helper_comment(seam, settings,
                        "Chart-Based seam generation using the Organic / Cloth preset.")

        unwrap = layout.box()
        unwrap.label(text="2. Unwrap")
        action = unwrap.column(align=True)
        action.enabled = targets.editable_count > 0
        action.operator("autoseamuv.simple_auto_unwrap", text="Auto Unwrap", icon="UV")
        _helper_comment(unwrap, settings, "Uses the current seams.")
        _helper_comment(unwrap, settings,
                        "Uses the active UV map, or creates UVMap if none exists.")
        if targets.missing_uv_count:
            _helper_comment(unwrap, settings,
                            "Missing UV maps will be created as UVMap.")

        layout_box = layout.box()
        layout_box.label(text="3. Layout")
        action = layout_box.column(align=True)
        action.enabled = targets.editable_count > 0 and targets.all_uv_ready
        action.operator("autoseamuv.simple_auto_layout", text="Auto Layout", icon="NODE_CORNER")
        _helper_comment(layout_box, settings,
                        "Scale and pack existing UV islands using Weighted Layout.")
        _helper_comment(layout_box, settings, "Seams and unwrap are not changed.")
        _helper_comment(layout_box, settings,
                        "Multiple objects will be packed into one Shared Weighted Atlas."
                        if targets.unique_mesh_count > 1 else
                        "One unique mesh target will use Weighted Layout.")
        if targets.editable_count and not targets.all_uv_ready:
            _error(layout_box, "%d selected mesh target(s) have no active UV map.",
                   targets.missing_uv_count)

        symmetry = layout.box()
        symmetry.label(text="4. Symmetry")
        symmetry.prop(settings, "simple_symmetry_axis", text="Axis")
        symmetry.prop(settings, "simple_symmetry_direction", text="Source Side")
        symmetry.label(text="Layout: Overlap")
        action = symmetry.column(align=True)
        action.enabled = targets.editable_count > 0 and targets.all_uv_ready
        action.operator("autoseamuv.simple_auto_symmetry", text="Auto Symmetry", icon="MOD_MIRROR")
        _helper_comment(symmetry, settings,
                        "Copies the source-side UVs onto the mirrored side.")
        _helper_comment(symmetry, settings, "Mirrored UVs are intentionally stacked.")
        _helper_comment(symmetry, settings,
                        "If this is run after Auto Layout, unused space may remain in the current atlas.")
        _helper_comment(symmetry, settings,
                        "Use this when both sides should share texture space.")
        if targets.editable_count and not targets.all_uv_ready:
            _error(symmetry, "%d selected mesh target(s) have no active UV map.",
                   targets.missing_uv_count)

    @staticmethod
    def _draw_seam(layout, settings, context, edit_mode, selected_faces, selected_edges):
        box = layout.box()
        if not _stage_header(box, settings, "show_stage_seam", "1. Seam"):
            return
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
            box.prop(settings, "max_chart_distortion", text="Max Distortion")
            box.prop(settings, "preserve_existing_seams", text="Preserve Existing Seams")
            descriptions = {
                "ORGANIC": "Fewer seams, garment structure and UV quality prioritized.",
                "HARD_SURFACE": "Sharp angles, material boundaries and hard edges prioritized.",
                "CYLINDER": "Topology-flow longitudinal seams prioritized.",
                "MANUAL": "Force / Protect / existing seams prioritized.",
            }
            _helper_comment(box, settings, descriptions[settings.seam_preset])
            row = box.row(align=True)
            row.operator("autoseamuv.analyze_seams", text="Analyze Seams", icon="VIEWZOOM")
            row.operator("autoseamuv.generate_seams", text="Generate Seams", icon="MOD_UVPROJECT")

        box.prop(settings, "show_seam_assist", toggle=True)
        if settings.show_seam_assist:
            assist = box.column(align=True)
            assist.label(text="Seam Assist — Active Object")
            AUTOSEAMUV_PT_panel._draw_seam_assist(
                assist, settings, edit_mode, selected_faces, selected_edges)

        if settings.seam_mode == "CLASSIC":
            box.prop(settings, "show_seam_advanced", text="Advanced", toggle=True)
            if settings.show_seam_advanced:
                advanced = box.column(align=True)
                advanced.prop(settings, "clear_existing")
                advanced.prop(settings, "longitudinal_seam_helper")
        else:
            box.prop(settings, "show_seam_advanced", text="Candidate Search", toggle=True)
            if settings.show_seam_advanced:
                advanced = box.column(align=True)
                advanced.prop(settings, "seam_count_penalty")
                advanced.prop(settings, "seam_minimum_spacing")
                advanced.prop(settings, "straightness_bias")
                advanced.prop(settings, "curvature_bias")
                advanced.prop(settings, "seam_search_radius")
                advanced.prop(settings, "chart_refinement_iterations")
                advanced.prop(settings, "use_distortion_guided_candidates")
                advanced.prop(settings, "use_edge_loop_completion")
            box.prop(settings, "show_garment_prior", toggle=True)
            if settings.show_garment_prior:
                garment = box.column(align=True)
                garment.prop(settings, "use_professional_garment_prior",
                             text="Professional Garment Prior")
                if settings.use_professional_garment_prior:
                    garment.prop(settings, "character_front_axis")
                    garment.prop(settings, "weight_material")

    @staticmethod
    def _draw_seam_assist(assist, settings, edit_mode, selected_faces, selected_edges):
        assist.prop(settings, "include_open_boundaries", text="Include Open Boundaries")
        row = assist.row(align=True)
        boundary_action = row.row()
        boundary_action.enabled = edit_mode and selected_faces > 0
        boundary = boundary_action.operator("autoseamuv.mark_selected_region_boundary", text="Selected Boundary", icon="EDGESEL")
        boundary.include_open_boundaries = settings.include_open_boundaries
        mirror_action = row.row()
        mirror_action.enabled = not (settings.mirror_direction == "SELECTED" and
                                     (not edit_mode or selected_edges == 0))
        mirror_action.operator("autoseamuv.mirror_seams", text="Mirror Seam State")
        mirror = assist.row(align=True)
        mirror.prop(settings, "mesh_symmetry_axis", text="Mesh Symmetry Axis")
        mirror.prop(settings, "mesh_symmetry_tolerance", text="Tolerance")
        mirror.prop(settings, "mirror_direction", text="Direction")
        if settings.mirror_direction == "SELECTED" and (not edit_mode or selected_edges == 0):
            _warning(assist, "Selected Side mirroring requires Edit Mode with selected edges.")
        if settings.seam_mode != "CLASSIC":
            assist.label(text="Selected Edges")
            row = assist.row(align=True)
            row.enabled = edit_mode and selected_edges > 0
            row.operator("autoseamuv.force_seam", text="Force")
            row.operator("autoseamuv.protect_seam", text="Protect")
            if not edit_mode or selected_edges == 0:
                _warning(assist, "Force / Protect requires Edit Mode and selected edges.")
            assist.label(text="Active Object")
            assist.operator("autoseamuv.clear_edge_tags", text="Clear All Tags")

    @staticmethod
    def _draw_unwrap(layout, settings, edit_mode, active_uv, context):
        box = layout.box()
        if not _stage_header(box, settings, "show_stage_unwrap", "2. Unwrap"):
            return
        box.prop(settings, "unwrap_method", text="Method")
        box.prop(settings, "unwrap_margin_method", text="Margin Method")
        if settings.unwrap_margin_method == "FRACTION":
            box.prop(settings, "unwrap_margin_percent", text="Unwrap Margin (%)")
        else:
            box.prop(settings, "unwrap_margin", text="Unwrap Margin")
        box.label(text="Scope: Selected UV Islands")
        selected_face_count = _selected_face_count(context)
        selected = box.column()
        selected.enabled = edit_mode and selected_face_count > 0 and active_uv is not None
        selected.operator("autoseamuv.unwrap_selected_faces",
                          text="Unwrap Selected UV Islands", icon="FACESEL")
        if not edit_mode:
            _warning(box, "Selected UV Islands requires Edit Mode.")
        elif selected_face_count == 0:
            _warning(box, "Select at least one face to seed UV islands.")
        elif active_uv is None:
            _warning(box, "Unwrap Selected UV Islands requires an existing active UV map.")
        box.operator("autoseamuv.unwrap_only", text="Unwrap Selected Objects", icon="UV")

        box.prop(settings, "show_unwrap_advanced", text="UV Map", toggle=True)
        if settings.show_unwrap_advanced:
            post = box.column(align=True)
            post.prop(settings, "uv_map_name", text="UV Map Name")
            post.prop(settings, "create_uv_if_missing", text="Create UV If Missing")
            _helper_comment(post, settings, "Named settings apply to Selected Objects and Ring / Strip.")
            _helper_comment(post, settings, "Selected UV Islands always uses Active UV and never creates one.")

        box.prop(settings, "show_post_unwrap", toggle=True)
        if settings.show_post_unwrap:
            post = box.column(align=True)
            post.prop(settings, "average_islands", text="Average Island Scale")
            post.prop(settings, "straighten_circular_strip_islands", text="Straighten Circular Strip Islands")

        box.prop(settings, "show_ring_strip", toggle=True)
        if settings.show_ring_strip:
            ring = box.column(align=True)
            ring.label(text="UV Target: Named UV Map", icon="INFO")
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
        if not _stage_header(box, settings, "show_stage_layout", "3. Layout"):
            return
        protection = box.column(align=True)
        protection.label(text="UV Protection", icon="LOCKED")
        protection.label(text="Target: Active Object", icon="INFO")
        has_faces = _selected_face_count(context) > 0
        row = protection.row(align=True)
        row.enabled = edit_mode and active_uv is not None and has_faces
        row.operator("autoseamuv.mark_finished_islands", text="Mark Finished")
        row.operator("autoseamuv.unmark_finished_islands", text="Unmark Finished")
        row = protection.row(align=True)
        row.enabled = edit_mode and active_uv is not None and has_faces
        row.operator("autoseamuv.lock_layout_islands", text="Lock Layout")
        row.operator("autoseamuv.unlock_layout_islands", text="Unlock Layout")
        protection.prop(settings, "show_protection_maintenance", toggle=True)
        if settings.show_protection_maintenance:
            row = protection.row(align=True)
            row.operator("autoseamuv.select_finished_islands", text="Select Finished")
            row.operator("autoseamuv.select_layout_locked_islands", text="Select Layout Locked")
            protection.operator("autoseamuv.clear_uv_protection", text="Clear UV Protection")
        if edit_mode and active_uv is not None and not has_faces:
            _warning(protection, "Select at least one face to seed UV islands.")
        protection.separator()
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
        weighted.prop(settings, "weighted_scale_mode", text="Scale Mode")
        weighted.prop(settings, "weighted_density_influence", text="Density Influence")
        weighted.separator()
        weighted.label(text="Padding")
        weighted.prop(settings, "weighted_padding_mode", text="Mode")
        if settings.weighted_padding_mode == "RELATIVE":
            weighted.prop(settings, "weighted_padding_uv_percent", text="UV Margin (%)")
        else:
            weighted.prop(settings, "weighted_padding_pixels", text="Padding")
            weighted.prop(settings, "weighted_texture_resolution", text="Texture Resolution")
        weighted.separator()
        weighted.label(text="Packing")
        weighted.prop(settings, "weighted_rotation_mode", text="Island Rotation")
        seed_map = selected_face_seeds_by_mesh(context, meshes)
        has_weighted_seeds = any(seed_map.values())
        selected_scope_ready = has_weighted_seeds and all(
            obj.data.polygons and obj.data.uv_layers.active is not None
            for obj in meshes if seed_map.get(obj.data.as_pointer()))
        if settings.weighted_scope == "SELECTED_FACES" and not edit_mode:
            _warning(weighted, "Selected UV Islands requires Edit Mode.")
        elif settings.weighted_scope == "SELECTED_FACES" and not has_weighted_seeds:
            _warning(weighted, "Select at least one face to seed UV islands.")
        action = weighted.row()
        action.enabled = (preflight["all_ready"] if settings.weighted_scope != "SELECTED_FACES"
                          else edit_mode and selected_scope_ready)
        action.operator("autoseamuv.weighted_island_layout", text="Weighted Island Layout")
        box.prop(settings, "show_incremental_layout", toggle=True)
        if settings.show_incremental_layout:
            incremental_box = box.column(align=True)
            incremental_box.label(text="Target: Active Object", icon="INFO")
            incremental_box.label(text="Scope: Selected UV Islands", icon="INFO")
            incremental = incremental_box.row()
            active = getattr(context, "active_object", None)
            incremental.enabled = bool(active and active.type == "MESH" and edit_mode and
                                       active.data.polygons and active_uv is not None and has_faces)
            incremental.operator("autoseamuv.pack_selected_into_free_space",
                                 text="Pack Selected Into Free Space")

        box.prop(settings, "show_shared_atlas", toggle=True)
        if settings.show_shared_atlas:
            shared_box = box.column(align=True)
            shared_box.label(text="Target: Selected Objects", icon="INFO")
            shared = shared_box.row()
            shared.enabled = (preflight["all_ready"] and preflight["unique_mesh_count"] >= 2 and
                              not (settings.weighted_scope == "SELECTED_FACES" and
                                   (not edit_mode or not has_weighted_seeds)))
            shared.operator("autoseamuv.shared_weighted_atlas", text="Shared Weighted Atlas")
            _helper_comment(shared_box, settings, "All selected objects share one weighted atlas.")

        pack = box.column(align=True)
        pack.prop(settings, "show_standard_pack", toggle=True)
        if not settings.show_standard_pack:
            pack = None
        else:
            pack = pack.column(align=True)
        if pack is not None:
            if settings.weighted_target_region in {"LEFT_HALF", "RIGHT_HALF"}:
                _warning(pack, "Half-region layout is active. Packing may break the Exact Texture-X workflow.")
            pack.prop(settings, "pack_rotation", text="Rotation")
            pack.prop(settings, "pack_margin_method", text="Margin Method")
            if settings.pack_margin_method == "FRACTION":
                pack.prop(settings, "pack_margin_percent", text="Pack Margin (%)")
            else:
                pack.prop(settings, "pack_margin", text="Pack Margin")
            pack.prop(settings, "show_pack_advanced", toggle=True)
            if settings.show_pack_advanced:
                advanced = pack.column(align=True)
                advanced.prop(settings, "pack_shape_method", text="Shape Method")
                advanced.prop(settings, "lock_pinned_islands", text="Lock Pinned Islands")
                if settings.lock_pinned_islands:
                    advanced.prop(settings, "pack_pin_method", text="Pin Method")
                advanced.prop(settings, "merge_overlapping", text="Merge Overlapping")
                advanced.prop(settings, "pack_target", text="Pack Target")
            protection_active = any(has_active_uv_protection(obj.data) for obj in meshes)
            if protection_active:
                _warning(pack, "Pack Islands cannot preserve UV Protection. Use Weighted Island Layout or Pack Selected Into Free Space, or clear UV Protection first.")
            action = pack.row()
            action.enabled = preflight["all_ready"] and not protection_active
            action.operator("autoseamuv.pack_islands", text="Pack Islands")

        atlas = box.column(align=True)
        atlas.prop(settings, "show_atlas_settings", toggle=True)
        if settings.show_atlas_settings:
            atlas_settings = atlas.column(align=True)
            atlas_settings.prop(settings, "atlas_uv_source", text="UV Source")
            if settings.atlas_uv_source == "NAMED":
                _helper_comment(atlas_settings, settings, "Named UV details are configured in UV Map.")
            else:
                atlas_settings.label(text="UV Target: each object's active UV map", icon="INFO")
            atlas_settings.prop(settings, "atlas_texture_resolution", text="Texture Resolution")
            atlas_settings.prop(settings, "atlas_pixel_margin", text="Pixel Margin")
            atlas_settings.prop(settings, "show_atlas_advanced", toggle=True)
            if settings.show_atlas_advanced:
                atlas_settings.prop(settings, "atlas_average_island_scale", text="Average Island Scale")
                if (settings.weighted_scale_mode == "ALLOCATE_BY_IMPORTANCE" and
                        settings.atlas_average_island_scale):
                    _warning(atlas_settings, "Average Island Scale may override the relative scaling created by Weighted Island Layout.")
                atlas_settings.prop(settings, "atlas_pack_rotate", text="Allow Rotation")
            atlas_preflight = resolve_atlas_targets(context, settings)
            atlas_protected = any(has_active_uv_protection(obj.data)
                                  for obj in atlas_preflight["objects"])
            if atlas_protected:
                _warning(atlas, "Atlas Pack cannot preserve UV Protection on the selected objects. Use Shared Weighted Atlas or clear UV Protection first.")
            action = atlas.row()
            action.enabled = atlas_preflight["all_ready"] and not atlas_protected
            action.operator("autoseamuv.atlas_pack_selected_objects", text="Atlas Pack Selected Objects")

    @staticmethod
    def _draw_symmetry(layout, settings, active_uv, edit_mode, selected_faces):
        box = layout.box()
        if not _stage_header(box, settings, "show_stage_symmetry", "4. Symmetry"):
            return
        mesh = box.column(align=True)
        mesh.label(text="Mesh Symmetry")
        mesh.label(text="Target: Active Object", icon="INFO")
        mesh.prop(settings, "mesh_symmetry_axis", text="Mesh Symmetry Axis")
        mesh.prop(settings, "symmetry_direction", text="Mesh Source Side")
        mesh.prop(settings, "symmetry_scope", text="Faces")
        mesh.prop(settings, "mesh_symmetry_tolerance", text="Mesh Symmetry Tolerance")
        if settings.symmetry_scope == "SELECTED" and (not edit_mode or selected_faces == 0):
            _warning(mesh, "Selected Faces requires Edit Mode.")
        symmetry_available = not (settings.symmetry_scope == "SELECTED" and
                                  (not edit_mode or selected_faces == 0))
        action = mesh.row()
        action.enabled = symmetry_available
        action.operator("autoseamuv.validate_symmetry", text="Validate Symmetry")

        standard = box.column(align=True)
        standard.separator()
        standard.label(text="Standard UV Transfer")
        standard.prop(settings, "symmetry_layout", text="Layout")
        if settings.symmetry_layout == "SEPARATE_MIRRORED":
            standard.prop(settings, "symmetry_island_gap_percent", text="Island Gap (%)")
        action = standard.row()
        action.enabled = active_uv is not None and symmetry_available
        action.operator("autoseamuv.transfer_symmetric_uv", text="Transfer Symmetric UV")

        island_sync = box.column(align=True)
        island_sync.separator()
        island_sync.label(text="Island Synchronization")
        island_sync.label(text="Source: Selected UV Island")
        island_sync.label(text="Mode: Copy Exact")
        island_sync.label(text="Synchronize Seams", icon="CHECKMARK")
        _helper_comment(island_sync, settings,
                        "Copies the selected island's UV coordinates and seam ON/OFF state to its mesh-symmetric counterpart.")
        _helper_comment(island_sync, settings, "The UV islands will overlap exactly.")
        action = island_sync.row()
        action.enabled = edit_mode and active_uv is not None and selected_faces > 0
        action.operator("autoseamuv.sync_mirrored_uv_island",
                        text="Synchronize Mirrored UV Island")

        box.prop(settings, "show_island_transform", toggle=True)
        if settings.show_island_transform:
            transform = box.column(align=True)
            transform.label(text="Target: Active Object")
            transform.label(text="Scope: Selected UV Islands")
            action = transform.row()
            action.enabled = edit_mode and active_uv is not None and selected_faces > 0
            action.operator("autoseamuv.flip_selected_uv_islands",
                            text="Flip Selected UV Islands")

        box.prop(settings, "show_exact_texture_x", toggle=True)
        if settings.show_exact_texture_x:
            exact = box.column(align=True)
            exact.prop(settings, "texture_source_side", text="Texture Source Side")
            target = settings.weighted_target_region
            source = settings.texture_source_side
            if target == "FULL":
                _warning(exact, "Exact Texture-X requires source UVs inside one texture half.")
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
        if not _stage_header(box, settings, "show_stage_validation", "5. Validation"):
            return
        overlap = box.column(align=True)
        overlap.operator("autoseamuv.check_uv_overlap", text="Check Overlap")
        quality = box.column(align=True)
        quality.operator("autoseamuv.validate_uv", text="Run UV Quality Check")
        box.prop(settings, "show_validation_settings", toggle=True)
        if settings.show_validation_settings:
            advanced = box.column(align=True)
            advanced.prop(settings, "check_overlap_across_objects", text="Check Across Objects")
            advanced.prop(settings, "stretch_warning_threshold", text="Stretch Warning Threshold")
            advanced.prop(settings, "overlap_area_epsilon", text="Zero-Area Tolerance")
            advanced.operator("autoseamuv.clear_uv_overlap_highlight",
                              text="Clear Overlap Selection")
            advanced.label(text="Last Quality Report")
            advanced.label(text=settings.report_summary, icon="INFO")


CLASSES = (AUTOSEAMUV_PT_panel,)
