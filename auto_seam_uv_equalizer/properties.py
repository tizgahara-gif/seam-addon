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

    seam_mode: EnumProperty(name="Detection Mode", items=(("CLASSIC", "Classic", "Fast, predictable independent edge rules"), ("ADVANCED", "Chart-Based", "Evaluate provisional UV charts and add only quality-improving cuts")), default="CLASSIC")
    seam_preset: EnumProperty(name="Seam Strategy", items=(("HARD_SURFACE", "Hard Surface", "Angle, sharp and material boundaries"), ("ORGANIC", "Organic / Cloth", "Long continuous low-noise cuts"), ("CYLINDER", "Cylinder / Cable", "End-to-end longitudinal path"), ("MANUAL", "Manual Assisted", "Force, protect and existing seams first")), default="HARD_SURFACE")
    weight_material: FloatProperty(name="Material Weight", default=1.5, min=0.0, max=10.0)
    seam_search_radius: IntProperty(name="Seam Search Radius", default=24, min=2, max=512)
    seam_minimum_spacing: IntProperty(name="Seam Minimum Spacing", default=3, min=0, max=128)
    straightness_bias: FloatProperty(name="Straightness Bias", default=0.6, min=0.0, max=5.0)
    max_chart_distortion: FloatProperty(name="Max Chart Distortion", default=0.18, min=0.0, max=2.0)
    seam_count_penalty: FloatProperty(name="Seam Count Penalty", default=0.08, min=0.0, max=2.0)
    chart_refinement_iterations: IntProperty(name="Refinement Iterations", default=5, min=1, max=8)
    preserve_existing_seams: BoolProperty(name="Preserve Existing Seams", default=True)
    show_seam_advanced: BoolProperty(name="Advanced", default=False)
    curvature_bias: FloatProperty(name="Curvature Bias", default=1.0, min=0.0, max=5.0)
    maintain_symmetry: BoolProperty(name="Maintain Symmetry", default=False)
    mirror_axis: EnumProperty(name="Mirror Axis", items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="X")
    mirror_tolerance: FloatProperty(name="Mirror Tolerance", default=0.0001, min=1e-7, max=0.1, precision=6)
    mirror_direction: EnumProperty(name="Direction", items=(("POSITIVE", "Positive to Negative", ""), ("NEGATIVE", "Negative to Positive", ""), ("SELECTED", "Selected Side to Opposite", "")), default="POSITIVE")
    symmetry_axis: EnumProperty(name="Axis", items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="X")
    symmetry_direction: EnumProperty(name="Source Side", items=(("NEGATIVE_TO_POSITIVE", "Negative to Positive", ""), ("POSITIVE_TO_NEGATIVE", "Positive to Negative", "")), default="NEGATIVE_TO_POSITIVE")
    symmetry_scope: EnumProperty(name="Scope", items=(("SELECTED", "Selected Faces", ""), ("WHOLE", "Whole Mesh", "")), default="SELECTED")
    symmetry_layout: EnumProperty(name="Layout", items=(("OVERLAP", "Overlap", ""), ("SEPARATE_MIRRORED", "Separate Mirrored", "")), default="OVERLAP")
    symmetry_tolerance: FloatProperty(name="Tolerance", default=0.0001, min=1e-7, max=0.1, precision=6)
    symmetry_island_gap: FloatProperty(name="Island Gap", default=0.02, min=0.0, max=10.0)
    texture_source_side: EnumProperty(
        name="Texture Source Side",
        items=(("LEFT_HALF", "Left Half", "Use UVs in the left texture half as the source"),
               ("RIGHT_HALF", "Right Half", "Use UVs in the right texture half as the source")),
        default="LEFT_HALF",
    )

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

    include_open_boundaries: BoolProperty(
        name="Include Open Boundaries",
        description="Include selected faces' edges on the open boundary of the mesh",
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

    ring_auto_detect: BoolProperty(
        name="Auto Detect",
        description="Recover the ring or strip grid from selected quad faces",
        default=True,
    )
    ring_layout: EnumProperty(
        name="Layout",
        items=(("RECTANGULAR", "Rectangular", "Align all rows to one width"),
               ("PRESERVE_CIRCUMFERENCE", "Preserve Circumference", "Retain each ring's measured 3D circumference")),
        default="PRESERVE_CIRCUMFERENCE",
    )
    ring_spacing: EnumProperty(
        name="Spacing",
        items=(("EVEN", "Even", "Use logical grid indices"),
               ("EDGE_LENGTH", "Edge Length", "Use individual 3D edge lengths"),
               ("AVERAGE_EDGE_LENGTH", "Average Edge Length", "Average corresponding edge intervals")),
        default="AVERAGE_EDGE_LENGTH",
    )
    ring_seam_mode: EnumProperty(
        name="Seam",
        items=(("EXISTING", "Existing", "Require one complete existing seam path"),
               ("SELECTED", "Selected", "Require one complete selected edge path"),
               ("AUTO", "Auto Best Seam", "Score all valid longitudinal paths")),
        default="AUTO",
    )
    ring_orientation: EnumProperty(
        name="Orientation",
        items=(("AUTO", "Auto", "Place the longitudinal direction on V"),
               ("HORIZONTAL", "Horizontal", "Place circumference on U"),
               ("VERTICAL", "Vertical", "Place circumference on V")),
        default="AUTO",
    )
    ring_normalize: BoolProperty(
        name="Normalize Result",
        description="Scale the generated island to fit one 0-1 square without changing its aspect ratio",
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

    weighted_density_influence: FloatProperty(
        name="Density Influence", default=0.25, min=0.0, max=1.0,
        description="Influence of median-normalized polygon density on island importance",
    )
    weighted_target_region: EnumProperty(
        name="Target UV Region",
        description="Choose which part of the 0-1 UV space the weighted layout may use.",
        items=(
            ("FULL", "Full 0-1", "Use the full 0-1 UV space"),
            ("LEFT_HALF", "Left Half", "Use U 0.0 through 0.5"),
            ("RIGHT_HALF", "Right Half", "Use U 0.5 through 1.0"),
        ),
        default="FULL",
    )
    weighted_scale_mode: EnumProperty(
        name="Scale Mode",
        items=(
            ("PRESERVE_TEXEL_DENSITY", "Preserve Texel Density", "Keep existing island scales unless one global scale is required"),
            ("ALLOCATE_BY_IMPORTANCE", "Allocate by Importance", "Scale islands so their UV areas follow importance weights, then pack their aspect-preserving bounds efficiently into the target UV region"),
        ),
        default="ALLOCATE_BY_IMPORTANCE",
    )
    weighted_scope: EnumProperty(
        name="Scope", items=(("SELECTED_FACES", "Selected Faces", "Only change selected faces"),
                             ("WHOLE_OBJECT", "Whole Object", "Change all faces")),
        default="WHOLE_OBJECT",
    )
    weighted_texture_size: IntProperty(
        name="Texture Size", default=2048, min=16, max=16384,
        description="Texture size used to convert padding pixels to UV units",
    )
    weighted_padding_pixels: IntProperty(
        name="Padding Pixels", default=4, min=0, max=1024,
        description="Padding reserved around each packed island bound in pixels",
    )


    atlas_texture_size: IntProperty(
        name="Atlas Texture Size",
        description="Texture size used to convert atlas pixel margin into UV margin",
        default=2048,
        min=16,
        max=16384,
    )

    atlas_uv_source: EnumProperty(
        name="Atlas UV Source",
        description="Choose each object's active UV map or the UV Map Name setting",
        items=(
            ("ACTIVE", "Active", "Pack each object's current active UV map; skip objects without one"),
            ("NAMED", "Named", "Pack UV Map Name and optionally create it when missing"),
        ),
        default="ACTIVE",
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
        name="Legacy Overlap Epsilon",
        description="Compatibility setting from versions before area and coordinate tolerances were separated",
        default=1.0e-6,
        min=0.0,
        max=0.01,
    )

    overlap_area_epsilon: FloatProperty(
        name="Overlap Area Epsilon",
        description="Minimum UV intersection area required to report an overlap",
        default=1.0e-6,
        min=0.0,
        max=0.01,
    )

    overlap_coord_epsilon: FloatProperty(
        name="Overlap Coordinate Epsilon",
        description="UV-coordinate tolerance used for bounds and clipping side tests",
        default=1.0e-9,
        min=0.0,
        max=0.01,
        precision=8,
    )

    check_overlap_across_objects: BoolProperty(
        name="Check Across Objects",
        description="Detect overlaps between different selected objects as well as within each object",
        default=True,
    )

    assign_overlap_debug_material: BoolProperty(
        name="Assign Overlap Debug Material",
        description="Legacy compatibility option; overlap highlighting is now non-destructive face selection",
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
