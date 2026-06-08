"""Addon settings for Auto Seam UV Equalizer."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty


class AUTOSEAMUV_PG_settings(bpy.types.PropertyGroup):
    """Scene-level settings used by the Auto Seam UV Equalizer operators."""

    angle_threshold: FloatProperty(
        name="Angle Threshold",
        description="Mark edges as seams when adjacent face normals meet or exceed this angle",
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

    unwrap_method: EnumProperty(
        name="Unwrap Method",
        description="Blender UV unwrap method",
        items=(
            ("ANGLE_BASED", "Angle Based", "Use Blender's angle based unwrap method"),
            ("CONFORMAL", "Conformal", "Use Blender's conformal unwrap method"),
        ),
        default="ANGLE_BASED",
    )
