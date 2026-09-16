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

    seam_mode: EnumProperty(name="Detection Mode", items=(("CLASSIC", "Classic", "Fast, predictable independent edge rules"), ("ADVANCED", "Chart-Based", "Evaluate provisional UV charts and add only quality-improving cuts")), default="ADVANCED")
    seam_preset: EnumProperty(name="Seam Strategy", items=(("HARD_SURFACE", "Hard Surface", "Angle, sharp and material boundaries"), ("ORGANIC", "Organic / Cloth", "Long continuous low-noise cuts"), ("CYLINDER", "Cylinder / Cable", "End-to-end longitudinal path"), ("MANUAL", "Manual Assisted", "Force, protect and existing seams first")), default="ORGANIC")
    weight_material: FloatProperty(name="Material Weight", default=1.5, min=0.0, max=10.0)
    seam_search_radius: IntProperty(name="Seam Search Radius", default=24, min=2, max=512)
    seam_minimum_spacing: IntProperty(name="Seam Minimum Spacing", default=3, min=0, max=128)
    straightness_bias: FloatProperty(name="Straightness Bias", default=0.6, min=0.0, max=5.0)
    max_chart_distortion: FloatProperty(name="Max Chart Distortion", default=0.18, min=0.0, max=2.0)
    seam_count_penalty: FloatProperty(name="Seam Count Penalty", default=0.08, min=0.0, max=2.0)
    chart_refinement_iterations: IntProperty(name="Refinement Iterations", default=5, min=1, max=8)
    preserve_existing_seams: BoolProperty(name="Preserve Existing Seams", default=True)
    show_seam_advanced: BoolProperty(name="Advanced", default=False)
    use_professional_garment_prior: BoolProperty(
        name="Use Professional Garment Prior", default=True,
        description="Ranks likely garment seam positions before trial unwrap. It never forces a seam; final acceptance is based on measured UV quality")
    use_distortion_guided_candidates: BoolProperty(
        name="Distortion-Guided Candidates", default=True,
        description="Uses distortion from the current temporary unwrap to choose which candidate seam paths to trial first. Final seam acceptance still requires measured UV quality improvement")
    use_edge_loop_completion: BoolProperty(
        name="Follow Clean Edge Loops", default=True,
        description="Extends eligible seam candidates along clean topological edge loops to natural endpoints before trialing them. The original shorter candidate is also kept. Final acceptance still requires measured UV quality improvement")
    character_front_axis: EnumProperty(
        name="Character Front Axis",
        items=(("+X", "+X", ""), ("-X", "-X", ""),
               ("+Y", "+Y", ""), ("-Y", "-Y", "")), default="-Y")
    curvature_bias: FloatProperty(name="Curvature Bias", default=1.0, min=0.0, max=5.0)
    mesh_symmetry_axis: EnumProperty(name="Mesh Symmetry Axis", items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="X")
    # Legacy compatibility only. New backend code uses mesh_symmetry_axis.
    mirror_axis: EnumProperty(name="Mirror Axis", items=(("X", "X", ""), ("Y", "Y", ""), ("Z", "Z", "")), default="X")
    mirror_tolerance: FloatProperty(name="Mirror Tolerance", default=0.0001, min=1e-7, max=0.1, precision=6)
    mesh_symmetry_tolerance: FloatProperty(name="Mesh Symmetry Tolerance", default=0.0001, min=1e-7, max=0.1, precision=6)
    mirror_direction: EnumProperty(name="Direction", items=(("POSITIVE", "Positive to Negative", ""), ("NEGATIVE", "Negative to Positive", ""), ("SELECTED", "Selected Side to Opposite", "")), default="POSITIVE")
    # Legacy compatibility only. New backend code uses mesh_symmetry_axis.
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

    unwrap_margin: FloatProperty(
        name="Unwrap Margin", description="Island margin used by UV unwrap operations",
        default=0.015, min=0.0, max=0.2,
    )
    pack_margin: FloatProperty(
        name="Pack Margin", description="Island margin used by Pack Islands",
        default=0.015, min=0.0, max=0.2,
    )
    # Legacy compatibility only. New backend code uses the two margins above.
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
        description="Runs after Unwrap Selected Objects only. Does not affect Unwrap Selected Faces",
        default=False,
    )

    straighten_circular_strip_islands: BoolProperty(
        name="Straighten Circular Strip Islands",
        description="Runs after Unwrap Selected Objects only. Does not affect Unwrap Selected Faces",
        default=False,
    )

    show_ring_strip: BoolProperty(name="Ring / Strip", default=False)
    show_unwrap_advanced: BoolProperty(name="Post-Unwrap", default=False)
    show_pack_advanced: BoolProperty(name="Pack Advanced", default=False)
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
    weighted_allow_rotation: BoolProperty(
        name="Allow 90° Island Rotation",
        default=False,
        description=("Allows UV islands to rotate by 90 degrees during weighted packing "
                     "when doing so improves placement efficiency. Island scale and "
                     "importance are preserved"),
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
        name="Scope", items=(("SELECTED_FACES", "Selected UV Islands", "Process every UV island containing at least one selected mesh face"),
                             ("WHOLE_OBJECT", "Whole Object", "Change all faces")),
        default="WHOLE_OBJECT",
    )
    weighted_padding_mode: EnumProperty(
        name="Padding Mode",
        items=(
            ("RELATIVE", "Relative UV", "Use a resolution-independent UV-space margin"),
            ("PIXELS", "Pixels", "Convert a pixel margin using the selected texture resolution"),
        ),
        default="PIXELS",
    )
    weighted_padding_uv: FloatProperty(
        name="UV Margin", default=0.004, min=0.0, max=0.5, precision=6,
        description="Resolution-independent margin in UV space",
    )
    weighted_texture_resolution: EnumProperty(
        name="Texture Resolution",
        description="Used only to convert pixel padding into UV-space padding. It does not affect island weighting or UV area allocation.",
        items=tuple((value, value, f"{value} x {value}")
                    for value in ("512", "1024", "2048", "4096", "8192")),
        default="2048",
    )
    # Legacy compatibility only. Weighted layout code never reads this value.
    weighted_texture_size: IntProperty(
        name="Texture Size", default=2048, min=16, max=16384,
        description="Legacy texture size retained for settings migration",
    )
    weighted_padding_pixels: IntProperty(
        name="Padding Pixels", default=4, min=0, max=1024,
        description="Padding reserved around each packed island bound in pixels",
    )
    weighted_allow_rotation: BoolProperty(
        name="Allow 90° Island Rotation", default=False,
        description="Allow movable weighted-layout islands to rotate by 90 degrees",
    )


    atlas_texture_size: IntProperty(
        name="Atlas Texture Size",
        description="Used for Atlas Pack pixel-margin conversion",
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
    show_atlas_settings: BoolProperty(name="Atlas Settings", default=False)

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


    texture_width: IntProperty(name="Texture Width", default=2048, min=1, max=65536)
    texture_height: IntProperty(name="Texture Height", default=2048, min=1, max=65536)
    texel_unit: EnumProperty(name="Unit", items=(("PX_M", "px/m", "Pixels per metre"), ("PX_CM", "px/cm", "Pixels per centimetre")), default="PX_M")
    target_texel_density: FloatProperty(name="Target Density", default=1024.0, min=0.001)
    measured_texel_density: FloatProperty(name="Measured Density", default=0.0, min=0.0, precision=3)
    uv_zero_tolerance: FloatProperty(name="Zero Area Tolerance", default=1e-10, min=0.0, max=0.01, precision=10)
    stretch_warning_threshold: FloatProperty(name="Stretch Warning Threshold", default=2.0, min=1.0, max=100.0)
    report_summary: StringProperty(name="Last Quality Report", default="No report yet")
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
        description="When selected objects share the same Mesh datablock, process that shared mesh only once. Applies across seam, unwrap and layout operations",
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


def migrate_legacy_settings(settings):
    """Copy stored v0.7 values once; untouched defaults remain independent."""
    keys = set(settings.keys())
    if "weighted_padding_mode" not in keys and (
            "weighted_texture_size" in keys or "weighted_padding_pixels" in keys):
        settings.weighted_padding_mode = "PIXELS"
    if "weighted_texture_resolution" not in keys and "weighted_texture_size" in keys:
        legacy_resolution = str(int(settings.weighted_texture_size))
        if legacy_resolution in {"512", "1024", "2048", "4096", "8192"}:
            settings.weighted_texture_resolution = legacy_resolution
    if "margin" in keys:
        if "unwrap_margin" not in keys:
            settings.unwrap_margin = settings.margin
        if "pack_margin" not in keys:
            settings.pack_margin = settings.margin
    if "mesh_symmetry_axis" not in keys:
        if "symmetry_axis" in keys:
            settings.mesh_symmetry_axis = settings.symmetry_axis
        elif "mirror_axis" in keys:
            settings.mesh_symmetry_axis = settings.mirror_axis
    if "mesh_symmetry_tolerance" not in keys:
        if "symmetry_tolerance" in keys:
            settings.mesh_symmetry_tolerance = settings.symmetry_tolerance
        elif "mirror_tolerance" in keys:
            settings.mesh_symmetry_tolerance = settings.mirror_tolerance
