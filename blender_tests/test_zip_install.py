"""Exercise Blender's real Install from Disk and add-on enable path."""

from __future__ import annotations

import pathlib
import sys

import bpy


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1:]
    if len(arguments) != 1:
        raise RuntimeError("usage: blender ... --python test_zip_install.py -- ADDON.zip")
    archive = pathlib.Path(arguments[0]).resolve()
    if not archive.is_file():
        raise RuntimeError(f"add-on archive does not exist: {archive}")

    bpy.ops.preferences.addon_install(filepath=str(archive), overwrite=True)
    bpy.ops.preferences.addon_enable(module="auto_seam_uv_equalizer")

    import auto_seam_uv_equalizer as addon

    assert "auto_seam_uv_equalizer" in bpy.context.preferences.addons
    assert hasattr(bpy.types, "AUTOSEAMUV_PT_panel")
    assert hasattr(bpy.types.Scene, "autoseamuv_settings")
    assert addon._on_load_post in bpy.app.handlers.load_post

    bpy.ops.preferences.addon_disable(module="auto_seam_uv_equalizer")
    assert "auto_seam_uv_equalizer" not in bpy.context.preferences.addons
    assert addon._on_load_post not in bpy.app.handlers.load_post
    assert not bpy.app.timers.is_registered(addon._deferred_migrate_current_file)

    bpy.ops.preferences.addon_enable(module="auto_seam_uv_equalizer")
    assert "auto_seam_uv_equalizer" in bpy.context.preferences.addons
    assert hasattr(bpy.types, "AUTOSEAMUV_PG_settings")
    print("ZIP_INSTALL_LIFECYCLE_OK")


main()
