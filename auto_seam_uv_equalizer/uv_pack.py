"""Compatibility wrapper around Blender's maintained island packer."""


def pack(bpy, settings, margin=None):
    kwargs = {
        "margin": settings.pack_margin if margin is None else margin,
        "shape_method": settings.pack_shape_method,
        "rotate": settings.pack_rotation != "OFF",
        "margin_method": settings.pack_margin_method,
        "pin": settings.lock_pinned_islands,
        "pin_method": settings.pack_pin_method,
        "merge_overlap": settings.merge_overlapping,
        "udim_source": settings.pack_target,
    }
    if settings.pack_rotation != "OFF":
        kwargs["rotate_method"] = settings.pack_rotation
    # Never silently retry with a reduced argument set: every visible setting
    # must reach Blender's packer, or the operation must fail explicitly.
    return bpy.ops.uv.pack_islands(**kwargs)
