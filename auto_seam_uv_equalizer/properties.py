"""Addon settings for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty


class AUTOSEAMUV_PG_settings(bpy.types.PropertyGroup):
    """Scene-level settings used by the Auto Seam UV Equalizer operators."""

    angle_threshold: FloatProperty(
        name="Angle Threshold (Degrees)",
        description="Mark edges as seams when adjacent face normals meet or exceed this degree value",
        default=55.0,
        min=1.0,
        max=179.0,
    )

    seam_mode: EnumProperty(name="Detection Mode", items=(("CLASSIC", "Classic", "Independent edge rules"), ("ADVANCED", "Advanced Paths", "Score candidates and build continuous paths")), default="ADVANCED")
    seam_preset: EnumProperty(name="Seam Strategy", items=(("HARD_SURFACE", "Hard Surface", "Angle, sharp and material boundaries"), ("ORGANIC", "Organic / Cloth", "Long continuous low-noise cuts"), ("CYLINDER", "Cylinder / Cable", "End-to-end longitudinal path"), ("MANUAL", "Manual Assisted", "Force, protect and existing seams first")), default="HARD_SURFACE")
    weight_curvature: FloatProperty(name="Curvature Weight", default=1.0, min=0.0, max=10.0)
    weight_material: FloatProperty(name="Material Weight", default=1.5, min=0.0, max=10.0)
    weight_sharp: FloatProperty(name="Sharp Weight", default=1.5, min=0.0, max=10.0)
    weight_boundary: FloatProperty(name="Boundary Weight", default=0.75, min=0.0, max=10.0)
    weight_existing: FloatProperty(name="Existing Seam Weight", default=1.0, min=0.0, max=10.0)
    weight_length: FloatProperty(name="Edge Length Weight", default=0.15, min=0.0, max=10.0)
    seam_search_radius: IntProperty(name="Seam Search Radius", default=24, min=2, max=512)
    seam_minimum_spacing: IntProperty(name="Seam Minimum Spacing", default=3, min=0, max=128)
    straightness_bias: FloatProperty(name="Straightness Bias", default=0.6, min=0.0, max=5.0)
    curvature_bias: FloatProperty(name="Curvature Bias", default=1.0, min=0.0, max=5.0)
    existing_seam_attraction: FloatProperty(name="Existing Seam Attraction", default=0.8, min=0.0, max=5.0)
    boundary_attraction: FloatProperty(name="Boundary Attraction", default=0.5, min=0.0, max=5.0)
    maintain_symmetry: BoolProperty(name="Maintain Symmetry", default=False)
    mirror_axis: EnumProperty(name="Mirror Axis", items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="X")
    mirror_tolerance: FloatProperty(name="Mirror Tolerance", default=0.0001, min=1e-7, max=0.1, precision=6)
    mirror_direction: EnumProperty(name="Direction", items=(("POSITIVE", "Positive to Negative", ""), ("NEGATIVE", "Negative to Positive", ""), ("SELECTED", "Selected Side to Opposite", "")), default="POSITIVE")

    margin: FloatProperty(
        name="UV Margin",
        description="Island margin used for unwrap and pack operations",
        default=0.015,
        min=0.0,
        max=0.2,
    )

    uv_map_name: StringProperty(
        name="UV Map Name",
        description="UV map to create or use for automatic unwrap operations",
        default="UV_Auto",
    )

    clear_existing: BoolProperty(
        name="Clear Existing Seams",
        description="Remove existing seam marks before automatic seam detection",
        default=False,
    )

    create_uv_if_missing: BoolProperty(
        name="Create UV If Missing",
        description="Create the named UV map when it does not already exist",
        default=True,
    )

    material_boundary: BoolProperty(
        name="Mark Material Boundaries",
        description="Mark edges between faces with different material slots as seams",
        default=True,
    )

    boundary_edges: BoolProperty(
        name="Mark Boundary Edges",
        description="Mark open mesh boundary edges as seams",
        default=True,
    )

    non_manifold_edges: BoolProperty(
        name="Mark Non-Manifold Edges",
        description="Mark edges connected to three or more faces as seams",
        default=True,
    )

    longitudinal_seam_helper: BoolProperty(
        name="Mark Longitudinal Seam Helper",
        description="Add one heuristic lengthwise seam for cylinders, pipes, supports, and cable-like meshes",
        default=False,
    )

    average_islands: BoolProperty(
        name="Average Island Scale",
        description="Normalize UV island texel density after unwrapping",
        default=True,
    )

    straighten_circular_strip_islands: BoolProperty(
        name="Straighten Circular Strip Islands",
        description="Straighten circular or arc-shaped UV strip islands after unwrap",
        default=False,
    )

    circular_strip_min_faces: IntProperty(
        name="Circular Strip Min Faces",
        description="Minimum face count required to treat an island as a circular strip candidate",
        default=6,
        min=3,
        max=256,
    )

    circular_strip_margin: FloatProperty(
        name="Circular Strip Margin",
        description="Optional margin applied inside the normalized strip",
        default=0.0,
        min=0.0,
        max=0.2,
    )

    pack_islands: BoolProperty(
        name="Pack Islands",
        description="Pack UV islands into the 0-1 UV space after unwrapping",
        default=True,
    )

    equal_region_pack: BoolProperty(
        name="Equal Region Pack",
        description="Place each seam-delimited UV island into its own equal 0-1 UV region instead of using Blender Pack Islands",
        default=False,
    )

    equal_region_margin: FloatProperty(
        name="Equal Region Margin",
        description="Padding inside each equal UV region",
        default=0.02,
        min=0.0,
        max=0.45,
    )

    equal_region_layout: EnumProperty(
        name="Equal Region Layout",
        description="Layout used when Equal Region Pack is enabled",
        items=(
            ("SQUARE_GRID", "Square Grid", "Use a near-square grid such as 2x2 for four islands"),
            ("HORIZONTAL_STRIP", "Horizontal Strip", "Place all islands in one horizontal row"),
            ("VERTICAL_STRIP", "Vertical Strip", "Place all islands in one vertical column"),
        ),
        default="SQUARE_GRID",
    )


    grid_fit_to_cell: BoolProperty(
        name="Fit Islands to Grid Cells",
        description="Scale each Auto Unwrap Grid island to fill its grid cell while preserving aspect ratio",
        default=True,
    )

    grid_cell_margin: FloatProperty(
        name="Grid Cell Margin",
        description="Margin inside each Auto Unwrap Grid cell",
        default=0.02,
        min=0.0,
        max=0.2,
    )

    grid_cell_fill_ratio: FloatProperty(
        name="Grid Cell Fill Ratio",
        description="Additional scale multiplier for fitted islands inside Auto Unwrap Grid cells",
        default=1.0,
        min=0.1,
        max=1.0,
    )


    atlas_texture_size: IntProperty(
        name="Atlas Texture Size",
        description="Texture size used to convert atlas pixel margin into UV margin",
        default=2048,
        min=16,
        max=16384,
    )

    atlas_pixel_margin: IntProperty(
        name="Atlas Pixel Margin",
        description="Pixel margin used when atlas packing selected objects",
        default=1,
        min=0,
        max=64,
    )

    atlas_average_island_scale: BoolProperty(
        name="Average Island Scale Before Atlas Pack",
        description="Average island scale before packing selected objects into one atlas",
        default=True,
    )

    atlas_pack_rotate: BoolProperty(
        name="Allow Atlas Rotation",
        description="Allow UV island rotation during atlas packing",
        default=True,
    )

    overlap_epsilon: FloatProperty(
        name="Overlap Epsilon",
        description="Minimum positive UV area required to treat triangle intersections as overlap",
        default=1.0e-6,
        min=0.0,
        max=0.01,
    )

    check_overlap_across_objects: BoolProperty(
        name="Check Across Objects",
        description="Detect overlaps between different selected objects as well as within each object",
        default=True,
    )

    assign_overlap_debug_material: BoolProperty(
        name="Assign Overlap Debug Material",
        description="Assign MAT_UV_OVERLAP_DEBUG to detected overlapping faces as a destructive visual aid",
        default=False,
    )

    texture_width: IntProperty(name="Texture Width", default=2048, min=1, max=65536)
    texture_height: IntProperty(name="Texture Height", default=2048, min=1, max=65536)
    texel_unit: EnumProperty(name="Unit", items=(("PX_M", "px/m", "Pixels per metre"), ("PX_CM", "px/cm", "Pixels per centimetre")), default="PX_M")
    target_texel_density: FloatProperty(name="Target Density", default=1024.0, min=0.001)
    measured_texel_density: FloatProperty(name="Measured Density", default=0.0, min=0.0, precision=3)
    uv_zero_tolerance: FloatProperty(name="Zero Area Tolerance", default=1e-10, min=0.0, max=0.01, precision=10)
    stretch_warning_threshold: FloatProperty(name="Stretch Warning Threshold", default=2.0, min=1.0, max=100.0)
    report_summary: StringProperty(name="Last Quality Report", default="No report yet")
    relax_after_unwrap: BoolProperty(name="Relax After Unwrap", default=False)
    relax_iterations: IntProperty(name="Relax Iterations", default=3, min=1, max=100)
    preserve_boundary: BoolProperty(name="Preserve Boundary", default=True)
    respect_pins: BoolProperty(name="Respect Pins", default=True)
    pack_shape_method: EnumProperty(name="Shape Method", items=(("CONCAVE", "Exact", ""), ("CONVEX", "Convex", ""), ("AABB", "Bounding Box", "")), default="CONCAVE")
    pack_rotation: EnumProperty(name="Rotation", items=(("OFF", "Off", ""), ("ANY", "Any", ""), ("CARDINAL", "Cardinal", ""), ("AXIS_ALIGNED", "Axis Aligned", "")), default="ANY")
    pack_margin_method: EnumProperty(name="Margin Method", items=(("SCALED", "Scaled", ""), ("ADD", "Add", ""), ("FRACTION", "Fraction", "")), default="SCALED")
    lock_pinned_islands: BoolProperty(name="Lock Pinned Islands", default=False)
    pack_pin_method: EnumProperty(name="Pin Method", items=(("LOCKED", "Lock All", ""), ("ROTATION", "Lock Rotation", ""), ("ROTATION_SCALE", "Lock Rotation & Scale", "")), default="LOCKED")
    merge_overlapping: BoolProperty(name="Merge Overlapping", default=False)
    pack_target: EnumProperty(name="Pack Target", items=(("CLOSEST_UDIM", "Closest UDIM", ""), ("ACTIVE_UDIM", "Active UDIM", ""), ("ORIGINAL_AABB", "Original Bounding Box", ""), ("CUSTOM_REGION", "Custom Region", "")), default="CLOSEST_UDIM")
    grid_layout_mode: EnumProperty(name="Grid Mode", items=(("PRESERVE_SCALE", "Preserve Scale", "Move only"), ("FIT_OVERSIZED", "Fit Oversized Only", "Shrink only islands exceeding cells"), ("FIT_EACH", "Fit Each Cell", "Changes relative texel density")), default="PRESERVE_SCALE")
    seam_group_name: StringProperty(name="Seam Group", default="UV0")
    seam_group_apply_mode: EnumProperty(name="Apply Mode", items=(("REPLACE", "Replace", ""), ("MERGE", "Merge", "")), default="REPLACE")

    process_shared_mesh_once: BoolProperty(
        name="Process Shared Mesh Data Once",
        description="Process only the first selected object for each shared mesh datablock",
        default=True,
    )

    unwrap_method: EnumProperty(
        name="Unwrap Method",
        description="Blender UV unwrap method",
        items=(
            ("ANGLE_BASED", "Angle Based", "Use Blender's angle based unwrap method"),
            ("CONFORMAL", "Conformal", "Use Blender's conformal unwrap method"),
        ),
        default="ANGLE_BASED",
    )
