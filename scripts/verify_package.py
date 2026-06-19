#!/usr/bin/env python3
"""Verify packaged Blender add-on zip contents include required implementation tokens."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REQUIRED_TOKENS: dict[str, tuple[str, ...]] = {
    "auto_seam_uv_equalizer/properties.py": (
        "longitudinal_seam_helper",
        "straighten_circular_strip_islands",
        "circular_strip_min_faces",
        "circular_strip_margin",
        "process_shared_mesh_once",
        "atlas_texture_size",
        "atlas_pixel_margin",
        "atlas_average_island_scale",
        "atlas_pack_rotate",
        "overlap_epsilon",
        "check_overlap_across_objects",
        "assign_overlap_debug_material",
        "grid_fit_to_cell",
        "grid_cell_margin",
        "grid_cell_fill_ratio",
    ),
    "auto_seam_uv_equalizer/seam_detection.py": (
        "def mark_auto_seams",
        "def mark_longitudinal_seam_helper",
    ),
    "auto_seam_uv_equalizer/island_tools.py": (
        "def find_uv_islands",
        "def straighten_circular_strip_island",
        "def straighten_circular_strip_islands_on_object",
    ),
    "auto_seam_uv_equalizer/uv_tools.py": (
        "def unwrap_object",
        "def unwrap_object_pack",
        "straighten_circular_strip_islands_on_object",
        "def equal_region_pack_object",
        "bpy.ops.uv.pack_islands",
    ),
    "auto_seam_uv_equalizer/operators.py": (
        "class AUTOSEAMUV_OT_auto_unwrap_pack",
        'bl_idname = "autoseamuv.auto_unwrap_pack"',
        'bl_label = "Auto Unwrap Grid"',
        'bl_label = "Auto Unwrap Pack"',
        "class AUTOSEAMUV_OT_atlas_pack_selected_objects",
        'bl_idname = "autoseamuv.atlas_pack_selected_objects"',
        'bl_label = "Atlas Pack Selected Objects"',
        "class AUTOSEAMUV_OT_check_uv_overlap",
        'bl_idname = "autoseamuv.check_uv_overlap"',
        'bl_label = "Check UV Overlap"',
        'bl_label = "Auto Seam + Unwrap"',
        "mark_longitudinal_seam_helper",
    ),
    "auto_seam_uv_equalizer/ui.py": (
        "straighten_circular_strip_islands",
        "longitudinal_seam_helper",
        'actions_box.operator("autoseamuv.unwrap_only", text="Auto Unwrap Grid"',
        'actions_box.operator("autoseamuv.auto_unwrap_pack", text="Auto Unwrap Pack"',
        'actions_box.operator("autoseamuv.mark_and_unwrap"',
        'actions_box.operator("autoseamuv.atlas_pack_selected_objects", text="Atlas Pack Selected Objects"',
        'actions_box.operator("autoseamuv.check_uv_overlap", text="Check UV Overlap"',
        "overlap_epsilon",
        "check_overlap_across_objects",
        "assign_overlap_debug_material",
        "grid_fit_to_cell",
        "grid_cell_margin",
        "grid_cell_fill_ratio",
    ),
    "auto_seam_uv_equalizer/README.md": (
        "Auto Seam + Unwrap",
        "Auto Unwrap Grid",
        "Auto Unwrap Pack",
        "Atlas Pack Selected Objects",
        "Check UV Overlap",
        "Mark Longitudinal Seam Helper",
        "Straighten Circular Strip Islands",
        "Material UV Scale Rules",
        "Fit Islands to Grid Cells",
        "Grid Cell Margin",
    ),
}

REMOVED_FEATURE_LABEL = "Arrange " + "Selected UV Islands to Grid"
REMOVED_OPERATOR_CLASS = "AUTOSEAMUV_OT_" + "arrange" + "_selected_uv_islands_to_grid"
REMOVED_OPERATOR_ID = "autoseamuv." + "arrange" + "_selected_uv_islands_to_grid"
REMOVED_MARGIN_PROP = "arrange" + "_selected_grid_margin"
REMOVED_LAYOUT_PROP = "arrange" + "_selected_grid_layout"
REMOVED_DUPLICATE_PROP = "duplicate_uv_before_" + "arrange"

FORBIDDEN_TOKENS = (
    REMOVED_FEATURE_LABEL,
    REMOVED_OPERATOR_CLASS,
    REMOVED_OPERATOR_ID,
    REMOVED_MARGIN_PROP,
    REMOVED_LAYOUT_PROP,
    REMOVED_DUPLICATE_PROP,
    "def find" + "_selected_uv_islands",
    "def compute" + "_grid_cells",
    "def fit_uv" + "_island_to_cell",
    "def " + "arrange" + "_selected_uv_islands_to_grid",
)

TEXT_EXTENSIONS = (".py", ".md", ".yml", ".yaml", ".ps1", ".sh")


def _read_zip_text(archive: zipfile.ZipFile, member_name: str) -> str:
    try:
        data = archive.read(member_name)
    except KeyError as exc:
        raise RuntimeError(f"Missing required file in zip: {member_name}") from exc

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"Required file is not valid UTF-8: {member_name}") from exc


def verify_package(zip_path: Path) -> None:
    if not zip_path.is_file():
        raise RuntimeError(f"Package zip not found: {zip_path}")

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        if "auto_seam_uv_equalizer/__init__.py" not in names:
            raise RuntimeError("Zip does not contain auto_seam_uv_equalizer/__init__.py")

        bad_parent_entries = [name for name in names if name.startswith("seam-addon-main/")]
        if bad_parent_entries:
            raise RuntimeError("Zip contains an extra seam-addon-main/ parent folder")

        for member_name, tokens in REQUIRED_TOKENS.items():
            text = _read_zip_text(archive, member_name)
            for token in tokens:
                if token not in text:
                    raise RuntimeError(f"Missing token in {member_name}: {token}")
                print(f"OK: {member_name} contains {token}")

        text_member_names = [name for name in names if name.endswith(TEXT_EXTENSIONS)]
        for token in FORBIDDEN_TOKENS:
            hits = []
            for member_name in text_member_names:
                text = _read_zip_text(archive, member_name)
                if token in text:
                    hits.append(member_name)
            if hits:
                raise RuntimeError(f"Forbidden removed-feature token still exists: {token} -> {hits}")
            print(f"OK: removed token absent from package: {token}")

    print(f"Package verification passed: {zip_path}")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python scripts/verify_package.py auto_seam_uv_equalizer.zip", file=sys.stderr)
        return 2

    try:
        verify_package(Path(argv[1]))
    except Exception as exc:
        print(f"Package verification failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
