"""Addon settings for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty


class AUTOSEAMUV_PG_settings(bpy.types.PropertyGroup):
    """Scene-level settings used by the Auto Seam UV Equalizer operators."""

    angle_threshold: FloatProperty(
        name="Angle Threshold (Degrees)",
        description="Mark edges as seams when adjacent face normals meet or exceed this degree value",
        default=55.0,
        min=1.0,
        max=179.0,
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

    arrange_selected_grid_margin: FloatProperty(
        name="Selected Grid Margin",
        description="Padding inside each equal grid cell when arranging selected UV islands",
        default=0.02,
        min=0.0,
        max=0.45,
    )

    arrange_selected_grid_layout: EnumProperty(
        name="Selected Grid Layout",
        description="Grid layout for arranging selected UV islands without unwrapping",
        items=(
            ("SQUARE_GRID", "Square Grid", "Use a near-square grid such as 2x2 for four islands and 3x2 for five islands"),
            ("HORIZONTAL_STRIP", "Horizontal Strip", "Place selected islands in one horizontal row"),
            ("VERTICAL_STRIP", "Vertical Strip", "Place selected islands in one vertical column"),
        ),
        default="SQUARE_GRID",
    )

    duplicate_uv_before_arrange: BoolProperty(
        name="Duplicate UV Before Arrange",
        description="Duplicate the active UV map before arranging selected UV islands",
        default=False,
    )

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
