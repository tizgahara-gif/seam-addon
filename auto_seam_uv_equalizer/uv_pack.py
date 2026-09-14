"""Compatibility wrapper around Blender's maintained island packer."""
def pack(bpy, settings, margin=None):
    kwargs={"margin": settings.margin if margin is None else margin,
            "shape_method":settings.pack_shape_method,
            "rotate":settings.pack_rotation != "OFF",
            "rotate_method":settings.pack_rotation,
            "margin_method":settings.pack_margin_method,
            "pin":settings.lock_pinned_islands,
            "pin_method":settings.pack_pin_method,
            "merge_overlap":settings.merge_overlapping,
            "udim_source":settings.pack_target}
    try: return bpy.ops.uv.pack_islands(**kwargs)
    except TypeError: return bpy.ops.uv.pack_islands(margin=kwargs["margin"], rotate=kwargs["rotate"])
