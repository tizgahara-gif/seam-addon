#!/usr/bin/env python3
"""Verify packaged Blender add-on zip contents include required implementation tokens."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REQUIRED_TOKENS: dict[str, tuple[str, ...]] = {
    "auto_seam_uv_equalizer/properties.py": (
        "arrange_selected_grid_margin",
        "arrange_selected_grid_layout",
        "duplicate_uv_before_arrange",
    ),
    "auto_seam_uv_equalizer/island_tools.py": (
        "def find_selected_uv_islands",
        "def compute_grid_cells",
        "def fit_uv_island_to_cell",
        "def arrange_selected_uv_islands_to_grid",
    ),
    "auto_seam_uv_equalizer/operators.py": (
        "class AUTOSEAMUV_OT_arrange_selected_uv_islands_to_grid",
        'bl_idname = "autoseamuv.arrange_selected_uv_islands_to_grid"',
    ),
    "auto_seam_uv_equalizer/__init__.py": (
        "operators.AUTOSEAMUV_OT_arrange_selected_uv_islands_to_grid",
    ),
    "auto_seam_uv_equalizer/ui.py": (
        "autoseamuv.arrange_selected_uv_islands_to_grid",
    ),
    "auto_seam_uv_equalizer/README.md": (
        "Arrange Selected UV Islands to Grid",
    ),
}


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
