"""Argument-level regression tests for Blender's Pack Islands wrapper."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace


SPEC = spec_from_file_location(
    "uv_pack", Path(__file__).parents[1] / "auto_seam_uv_equalizer" / "uv_pack.py"
)
uv_pack = module_from_spec(SPEC)
SPEC.loader.exec_module(uv_pack)


class PackRecorder:
    def __init__(self):
        self.calls = []
        self.ops = SimpleNamespace(uv=SimpleNamespace(pack_islands=self.pack_islands))

    def pack_islands(self, **kwargs):
        self.calls.append(kwargs)
        return {"FINISHED"}


def settings(rotation):
    return SimpleNamespace(
        pack_margin=0.125,
        pack_shape_method="CONVEX",
        pack_rotation=rotation,
        pack_margin_method="FRACTION",
        lock_pinned_islands=True,
        pack_pin_method="ROTATION",
        merge_overlapping=True,
        pack_target="ACTIVE_UDIM",
    )


def test_rotation_off_omits_only_rotate_method():
    bpy = PackRecorder()

    assert uv_pack.pack(bpy, settings("OFF")) == {"FINISHED"}

    assert bpy.calls == [{
        "margin": 0.125,
        "shape_method": "CONVEX",
        "rotate": False,
        "margin_method": "FRACTION",
        "pin": True,
        "pin_method": "ROTATION",
        "merge_overlap": True,
        "udim_source": "ACTIVE_UDIM",
    }]


def test_enabled_rotation_methods_are_forwarded():
    for rotation in ("ANY", "CARDINAL"):
        bpy = PackRecorder()
        assert uv_pack.pack(bpy, settings(rotation)) == {"FINISHED"}
        assert bpy.calls[0]["rotate"] is True
        assert bpy.calls[0]["rotate_method"] == rotation
