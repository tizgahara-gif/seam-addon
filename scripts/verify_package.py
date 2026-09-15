#!/usr/bin/env python3
"""Verify packaged Blender add-on zip contents include required implementation tokens."""

from __future__ import annotations

import sys
import ast
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
        "atlas_uv_source",
        "atlas_pixel_margin",
        "atlas_average_island_scale",
        "atlas_pack_rotate",
        "overlap_epsilon",
        "overlap_area_epsilon",
        "overlap_coord_epsilon",
        "check_overlap_across_objects",
        "assign_overlap_debug_material",
        "weighted_density_influence",
        "weighted_target_region",
        "weighted_scale_mode",
        "weighted_padding_pixels",
        "include_open_boundaries",
        "symmetry_layout",
        "symmetry_scope",
        "texture_source_side",
    ),
    "auto_seam_uv_equalizer/seam_detection.py": (
        "def mark_auto_seams",
        "def mark_longitudinal_seam_helper",
        "def mark_advanced_seams",
    ),
    "auto_seam_uv_equalizer/island_tools.py": (
        "def find_uv_islands",
        "def straighten_circular_strip_island",
        "def straighten_circular_strip_islands_on_object",
    ),
    "auto_seam_uv_equalizer/uv_tools.py": (
        "def unwrap_object",
        "def pack_object",
        "straighten_circular_strip_islands_on_object",
        "blender_pack",
    ),
    "auto_seam_uv_equalizer/weighted_layout.py": (
        "def calculate_weights", "def importance_boxes", "def pack_importance_boxes",
        "def _maxrects_pack", "def weighted_layout_object",
        "DENSITY_MIN = 0.25", "DENSITY_MAX = 4.0", "find_uv_islands",
    ),
    "auto_seam_uv_equalizer/operators.py": (
        "class AUTOSEAMUV_OT_auto_unwrap_pack",
        'bl_idname = "autoseamuv.auto_unwrap_pack"',
        'bl_label = "Auto Unwrap"',
        "class AUTOSEAMUV_OT_weighted_island_layout",
        'bl_idname = "autoseamuv.weighted_island_layout"',
        "class AUTOSEAMUV_OT_pack_islands",
        "class AUTOSEAMUV_OT_atlas_pack_selected_objects",
        'bl_idname = "autoseamuv.atlas_pack_selected_objects"',
        'bl_label = "Atlas Pack Selected Objects"',
        "class AUTOSEAMUV_OT_check_uv_overlap",
        'bl_idname = "autoseamuv.check_uv_overlap"',
        'bl_label = "Check UV Overlap"',
        'bl_label = "Auto Seam + Unwrap"',
        'margin_method="FRACTION"',
        "mark_longitudinal_seam_helper",
        "class AUTOSEAMUV_OT_mark_selected_region_boundary",
        'bl_idname = "autoseamuv.mark_selected_region_boundary"',
        "def _auto_mark",
    ),
    "auto_seam_uv_equalizer/ui.py": (
        "straighten_circular_strip_islands",
        "longitudinal_seam_helper",
        'uv_box.operator("autoseamuv.unwrap_only", text="Auto Unwrap"',
        'weighted_box.operator("autoseamuv.weighted_island_layout", text="Weighted Island Layout"',
        'packing_box.operator("autoseamuv.pack_islands", text="Pack Islands"',
        'actions_box.operator("autoseamuv.auto_unwrap_pack", text="Auto Unwrap + Pack"',
        'actions_box.operator("autoseamuv.mark_and_unwrap"',
        'actions_box.operator("autoseamuv.atlas_pack_selected_objects", text="Atlas Pack Selected Objects"',
        'actions_box.operator("autoseamuv.check_uv_overlap", text="Check UV Overlap"',
        "overlap_area_epsilon",
        "overlap_coord_epsilon",
        "check_overlap_across_objects",
        "weighted_scale_mode",
        "weighted_target_region",
        "weighted_padding_pixels",
        'actions_box.prop(settings, "include_open_boundaries")',
        'symmetry_box.operator("autoseamuv.validate_symmetry"',
        'symmetry_box.operator("autoseamuv.transfer_symmetric_uv"',
        'symmetry_box.operator("autoseamuv.transfer_exact_texture_x_symmetry"',
    ),
    "auto_seam_uv_equalizer/symmetry.py": (
        "def build_symmetry_plan",
        "def transferred_uvs",
        "def exact_texture_x_uvs",
    ),
    "auto_seam_uv_equalizer/operators_symmetry.py": (
        'bl_idname = "autoseamuv.validate_symmetry"',
        'bl_idname = "autoseamuv.transfer_symmetric_uv"',
        "class AUTOSEAMUV_OT_transfer_exact_texture_x_symmetry",
        'bl_idname = "autoseamuv.transfer_exact_texture_x_symmetry"',
    ),
    "auto_seam_uv_equalizer/mesh_utils.py": (
        "def build_mesh_topology",
        "def build_edge_to_faces",
    ),
    "auto_seam_uv_equalizer/uv_validation.py": (
        "mesh.loop_triangles",
        "def find_overlaps",
        "def _candidate_pairs",
    ),
    "auto_seam_uv_equalizer/README.md": (
        "Auto Seam + Unwrap",
        "Weighted Island Layout",
        "Auto Unwrap + Pack",
        "Atlas Pack Selected Objects",
        "Check UV Overlap",
        "Mark Longitudinal Seam Helper",
        "Straighten Circular Strip Islands",
        "Material UV Scale Rules",
        "Preserve Texel Density",
        "Density Influence",
        "Mark Selected Region Boundary as Seam",
    ),
}

REMOVED_FEATURE_LABEL = "Arrange " + "Selected UV Islands to Grid"
REMOVED_OPERATOR_CLASS = "AUTOSEAMUV_OT_" + "arrange" + "_selected_uv_islands_to_grid"
REMOVED_OPERATOR_ID = "autoseamuv." + "arrange" + "_selected_uv_islands_to_grid"
REMOVED_MARGIN_PROP = "arrange" + "_selected_grid_margin"
REMOVED_LAYOUT_PROP = "arrange" + "_selected_grid_layout"
REMOVED_DUPLICATE_PROP = "duplicate_uv_before_" + "arrange"

FORBIDDEN_TOKENS = (
    "grid_layout_mode",
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
    "def weighted_rectangles",
    "def importance_scales",
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


def _classes_module_references(init_source: str) -> set[str]:
    """Return modules expanded as ``*module.CLASSES`` in the package registry."""
    tree = ast.parse(init_source, filename="auto_seam_uv_equalizer/__init__.py")
    references = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Starred):
            continue
        attribute = node.value
        if (isinstance(attribute, ast.Attribute)
                and attribute.attr == "CLASSES"
                and isinstance(attribute.value, ast.Name)):
            references.add(attribute.value.id)
    return references


def _defines_classes(module_source: str, filename: str) -> bool:
    """Check for a real module-level CLASSES assignment rather than a token."""
    tree = ast.parse(module_source, filename=filename)
    for statement in tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if any(isinstance(target, ast.Name) and target.id == "CLASSES"
                   for target in targets):
                return True
    return False


def _function_calls(module_source: str, filename: str) -> dict[str, set[str]]:
    """Return direct named calls made by each top-level function."""
    tree = ast.parse(module_source, filename=filename)
    calls = {}
    for statement in tree.body:
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls[statement.name] = {
            node.func.id
            for node in ast.walk(statement)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
    return calls


def _verify_weighted_layout_backend(module_source: str) -> None:
    """Require the production call chain for importance BBox packing."""
    filename = "auto_seam_uv_equalizer/weighted_layout.py"
    calls = _function_calls(module_source, filename)
    required = {
        "calculate_weights", "importance_boxes", "pack_importance_boxes",
        "_maxrects_pack", "weighted_layout_object",
    }
    missing = sorted(required - calls.keys())
    if missing:
        raise RuntimeError(f"Weighted Layout backend functions missing: {missing}")
    required_edges = {
        "weighted_layout_object": {"calculate_weights", "pack_importance_boxes"},
        "pack_importance_boxes": {"importance_boxes", "_maxrects_pack"},
    }
    for caller, callees in required_edges.items():
        missing_calls = sorted(callees - calls[caller])
        if missing_calls:
            raise RuntimeError(
                f"Weighted Layout backend {caller} does not call: {missing_calls}"
            )
    legacy = sorted({"weighted_rectangles", "importance_scales"} & calls.keys())
    if legacy:
        raise RuntimeError(f"Legacy Weighted Layout functions present: {legacy}")
    print("OK: Weighted Layout uses the importance BBox MaxRects backend")


def _verify_classes_registries(archive: zipfile.ZipFile) -> None:
    init_name = "auto_seam_uv_equalizer/__init__.py"
    init_source = _read_zip_text(archive, init_name)
    references = _classes_module_references(init_source)
    if not references:
        raise RuntimeError(f"No *module.CLASSES references found in {init_name}")
    for module_name in sorted(references):
        member_name = f"auto_seam_uv_equalizer/{module_name}.py"
        module_source = _read_zip_text(archive, member_name)
        if not _defines_classes(module_source, member_name):
            raise RuntimeError(
                f"{init_name} references {module_name}.CLASSES, but "
                f"{member_name} has no module-level CLASSES assignment"
            )
        print(f"OK: {module_name}.CLASSES is defined")


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

        _verify_classes_registries(archive)

        weighted_source = _read_zip_text(
            archive, "auto_seam_uv_equalizer/weighted_layout.py"
        )
        _verify_weighted_layout_backend(weighted_source)

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
