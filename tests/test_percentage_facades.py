"""Percentage façade contracts that do not require Blender."""

import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "auto_seam_uv_equalizer" / "percentage_facades.py"
SPEC = importlib.util.spec_from_file_location("percentage_facades", MODULE_PATH)
facades = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(facades)


def _round_trip(getter, setter, attribute, internal):
    settings = SimpleNamespace(**{attribute: internal})
    displayed = getter(settings)
    setter(settings, displayed)
    assert math.isclose(getattr(settings, attribute), internal, abs_tol=1.0e-12)


def test_weighted_uv_margin_conversion_and_legacy_value():
    settings = SimpleNamespace(weighted_padding_uv=0.004)
    assert facades.get_weighted_padding_uv_percent(settings) == 0.4
    facades.set_weighted_padding_uv_percent(settings, 0.75)
    assert settings.weighted_padding_uv == 0.0075


def test_symmetry_island_gap_conversion():
    settings = SimpleNamespace(symmetry_island_gap=0.03)
    assert facades.get_symmetry_island_gap_percent(settings) == 3.0
    facades.set_symmetry_island_gap_percent(settings, 2.5)
    assert settings.symmetry_island_gap == 0.025


def test_all_percentage_facades_round_trip_without_duplicate_state():
    cases = (
        (facades.get_weighted_padding_uv_percent,
         facades.set_weighted_padding_uv_percent, "weighted_padding_uv"),
        (facades.get_unwrap_margin_percent,
         facades.set_unwrap_margin_percent, "unwrap_margin"),
        (facades.get_pack_margin_percent,
         facades.set_pack_margin_percent, "pack_margin"),
        (facades.get_symmetry_island_gap_percent,
         facades.set_symmetry_island_gap_percent, "symmetry_island_gap"),
    )
    for getter, setter, attribute in cases:
        _round_trip(getter, setter, attribute, 0.00375)


def test_pixel_padding_contract_is_unchanged():
    settings = SimpleNamespace(
        weighted_padding_mode="PIXELS",
        weighted_padding_pixels=8,
        weighted_texture_resolution="2048",
        weighted_padding_uv=0.004,
    )
    # This is the unchanged backend contract: the percentage façade is not
    # consulted for pixel mode.
    resolved = settings.weighted_padding_pixels / int(settings.weighted_texture_resolution)
    assert resolved == 8 / 2048


def test_backend_modules_do_not_read_percentage_facades():
    allowed = {"properties.py", "ui.py", "percentage_facades.py"}
    offenders = []
    for path in (ROOT / "auto_seam_uv_equalizer").glob("*.py"):
        if path.name in allowed:
            continue
        if "_percent" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders


def test_mesh_symmetry_tolerance_stays_object_space_and_unconverted():
    properties = (ROOT / "auto_seam_uv_equalizer" / "properties.py").read_text()
    ui = (ROOT / "auto_seam_uv_equalizer" / "ui.py").read_text()
    symmetry = (ROOT / "auto_seam_uv_equalizer" / "symmetry.py").read_text()
    assert "mesh_symmetry_tolerance_percent" not in properties
    assert 'prop(settings, "mesh_symmetry_tolerance"' in ui
    assert "Maximum object-space distance in Blender units" in properties
    assert "tolerance_squared = tolerance * tolerance" in symmetry


def test_fraction_pack_uses_facade_but_backend_keeps_normalized_property():
    ui = (ROOT / "auto_seam_uv_equalizer" / "ui.py").read_text()
    backend = (ROOT / "auto_seam_uv_equalizer" / "uv_pack.py").read_text()
    assert 'settings.pack_margin_method == "FRACTION"' in ui
    assert 'prop(settings, "pack_margin_percent"' in ui
    assert 'prop(settings, "pack_margin", text="Pack Margin")' in ui
    assert '"margin": settings.pack_margin' in backend
