"""Unit conversions used by human-facing percentage properties.

The Blender RNA properties in :mod:`properties` remain the sole stored source
of truth.  Keeping this arithmetic Blender-free also makes the UI/backend
contract straightforward to test without constructing an RNA object.
"""

from __future__ import annotations


def normalized_to_percent(value: float) -> float:
    """Convert a normalized 0-1-space value to a percentage value."""
    return float(value) * 100.0


def percent_to_normalized(value: float) -> float:
    """Convert a human-entered percentage to its normalized backend value."""
    return float(value) / 100.0


def get_weighted_padding_uv_percent(settings) -> float:
    return normalized_to_percent(settings.weighted_padding_uv)


def set_weighted_padding_uv_percent(settings, value: float) -> None:
    settings.weighted_padding_uv = percent_to_normalized(value)


def get_unwrap_margin_percent(settings) -> float:
    return normalized_to_percent(settings.unwrap_margin)


def set_unwrap_margin_percent(settings, value: float) -> None:
    settings.unwrap_margin = percent_to_normalized(value)


def get_pack_margin_percent(settings) -> float:
    return normalized_to_percent(settings.pack_margin)


def set_pack_margin_percent(settings, value: float) -> None:
    settings.pack_margin = percent_to_normalized(value)


def get_symmetry_island_gap_percent(settings) -> float:
    return normalized_to_percent(settings.symmetry_island_gap)


def set_symmetry_island_gap_percent(settings, value: float) -> None:
    settings.symmetry_island_gap = percent_to_normalized(value)
