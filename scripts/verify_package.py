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
        "show_ring_strip",
        "weighted_density_influence",
        "weighted_allow_rotation",
        "weighted_target_region",
        "weighted_scale_mode",
        "weighted_padding_mode",
        "weighted_padding_uv",
        "weighted_texture_resolution",
        "weighted_padding_pixels",
        "include_open_boundaries",
        "symmetry_layout",
        "symmetry_scope",
        "texture_source_side",
        "unwrap_margin",
        "unwrap_margin_method",
        "pack_margin",
        "mesh_symmetry_axis",
        "use_distortion_guided_candidates",
    ),
    "auto_seam_uv_equalizer/seam_detection.py": (
        "def mark_auto_seams",
        "def mark_longitudinal_seam_helper",
        "def analyze_chart_seams",
        "def apply_chart_seams",
    ),
    "auto_seam_uv_equalizer/island_tools.py": (
        "def find_uv_islands",
        "def find_uv_face_islands",
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
        "def _maxrects_pack", "def weighted_layout_object", "def collect_weighted_islands",
        "def plan_weighted_layout", "def apply_weighted_plan", "def shared_weighted_layout",
        "def resolve_weighted_padding",
        "DENSITY_MIN = 0.25", "DENSITY_MAX = 4.0", "find_uv_islands",
    ),
    "auto_seam_uv_equalizer/operators.py": (
        "class AUTOSEAMUV_OT_auto_unwrap_pack",
        'bl_idname = "autoseamuv.auto_unwrap_pack"',
        'bl_label = "Auto Unwrap"',
        "class AUTOSEAMUV_OT_weighted_island_layout",
        'bl_idname = "autoseamuv.weighted_island_layout"',
        "class AUTOSEAMUV_OT_shared_weighted_atlas",
        'bl_idname = "autoseamuv.shared_weighted_atlas"',
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
        '_stage_header(box, settings, "show_stage_seam", "1. Seam")',
        '_stage_header(box, settings, "show_stage_unwrap", "2. Unwrap")',
        '_stage_header(box, settings, "show_stage_layout", "3. Layout")',
        '_stage_header(box, settings, "show_stage_symmetry", "4. Symmetry")',
        '_stage_header(box, settings, "show_stage_validation", "5. Validation")',
        '"autoseamuv.analyze_seams"',
        '"autoseamuv.generate_seams"',
        '"autoseamuv.weighted_island_layout"',
        '"autoseamuv.shared_weighted_atlas"',
        '"autoseamuv.pack_islands"',
    ),
    "auto_seam_uv_equalizer/symmetry.py": (
        "def build_symmetry_plan",
        "def transferred_uvs",
        "def exact_texture_x_uvs",
        "def collect_selected_source_uv_island",
        "def plan_mirrored_island_sync",
    ),
    "auto_seam_uv_equalizer/operators_symmetry.py": (
        'bl_idname = "autoseamuv.validate_symmetry"',
        'bl_idname = "autoseamuv.transfer_symmetric_uv"',
        "class AUTOSEAMUV_OT_transfer_exact_texture_x_symmetry",
        'bl_idname = "autoseamuv.transfer_exact_texture_x_symmetry"',
        "class AUTOSEAMUV_OT_sync_mirrored_uv_island",
        'bl_idname = "autoseamuv.sync_mirrored_uv_island"',
    ),
    "auto_seam_uv_equalizer/operators_uv.py": (
        "class AUTOSEAMUV_OT_flip_selected_uv_islands",
        'bl_idname = "autoseamuv.flip_selected_uv_islands"',
        'bl_options = {"REGISTER", "UNDO"}',
    ),
    "auto_seam_uv_equalizer/uv_island_flip.py": (
        "def collect_selected_uv_islands",
        "def plan_horizontal_uv_flip",
        "def apply_uv_plan",
        "find_uv_face_islands",
    ),
    "auto_seam_uv_equalizer/mesh_utils.py": (
        "def build_mesh_topology",
        "def build_edge_to_faces",
    ),
    "auto_seam_uv_equalizer/uv_validation.py": (
        "mesh.loop_triangles",
        "def build_uv_triangle_snapshot",
        "def validate_snapshot",
        "class UVValidationError",
        "def find_overlaps",
        "def _candidate_pairs",
    ),
    "auto_seam_uv_equalizer/README.md": (
        "Auto Seam UV Equalizer v0.9.0",
        "Five-stage panel",
        "Weighted Island Layout",
        "Atlas Pack Selected Objects",
        "Exact Texture-X",
        "Clear Overlap Selection",
        "Shared Weighted Atlas",
        "Distortion-Guided Seam Candidates",
        "Mirrored UV Island Synchronization",
    ),
    "auto_seam_uv_equalizer/chart_seam.py": (
        "def cached_uv_analysis_evaluators", "def uv_face_distortion_from_snapshot",
        "def distortion_hot_clusters", "def select_trial_paths",
        "DISTORTION_RESERVED_TRIALS = 2",
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
DEPRECATED_UV_PATTERNS = ("uv_layer.data[", ".uv_layers.active.data[")


def _verify_modern_uv_api(sources: dict[str, str]) -> None:
    for pattern in DEPRECATED_UV_PATTERNS:
        hits = sorted(name for name, source in sources.items() if pattern in source)
        if hits:
            raise RuntimeError(f"Deprecated UV API pattern {pattern!r}: {hits}")


def _verify_percentage_facade_routing(sources: dict[str, str]) -> None:
    """Keep percentage properties at the RNA/UI boundary, never in backends."""
    allowed = {
        "auto_seam_uv_equalizer/properties.py",
        "auto_seam_uv_equalizer/ui.py",
        "auto_seam_uv_equalizer/percentage_facades.py",
    }
    hits = sorted(name for name, source in sources.items()
                  if name not in allowed and "_percent" in source)
    if hits:
        raise RuntimeError(f"Backend reads percentage façade properties: {hits}")
    ui = sources.get("auto_seam_uv_equalizer/ui.py", "")
    uv_tools = sources.get("auto_seam_uv_equalizer/uv_tools.py", "")
    operators = sources.get("auto_seam_uv_equalizer/operators.py", "")
    if "unwrap_margin" in ui and not all(token in ui for token in (
            'settings.unwrap_margin_method == "FRACTION"',
            'prop(settings, "unwrap_margin_percent"',
            'prop(settings, "unwrap_margin", text="Unwrap Margin")')):
        raise RuntimeError("Unwrap Margin percentage façade is not conditional on Fraction")
    if uv_tools:
        tree = ast.parse(uv_tools, filename="auto_seam_uv_equalizer/uv_tools.py")
        functions = {node.name: node for node in tree.body
                     if isinstance(node, ast.FunctionDef)}
        for name in ("unwrap_object", "unwrap_selected_faces"):
            function = functions.get(name)
            calls = [] if function is None else [
                node for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "unwrap"]
            if not calls or not all(
                    {"method", "margin_method", "margin"} <=
                    {keyword.arg for keyword in call.keywords} for call in calls):
                raise RuntimeError(f"{name} does not route Blender unwrap margin_method")
    if operators and "settings.unwrap_margin_percent" in operators:
        raise RuntimeError("Unwrap backend reads percentage façade property")
    print("OK: percentage façades and Unwrap margin methods are routed correctly")


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
        "_maxrects_pack", "weighted_layout_object", "collect_weighted_islands",
        "plan_weighted_layout", "apply_weighted_plan", "shared_weighted_layout",
    }
    missing = sorted(required - calls.keys())
    if missing:
        raise RuntimeError(f"Weighted Layout backend functions missing: {missing}")
    required_edges = {
        "weighted_layout_object": {"collect_weighted_islands", "plan_weighted_layout", "apply_weighted_plan"},
        "shared_weighted_layout": {"collect_weighted_islands", "plan_weighted_layout", "apply_weighted_plan"},
        "plan_weighted_layout": {"calculate_weights", "pack_importance_boxes"},
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
        addon_sources = {name: _read_zip_text(archive, name) for name in names
                         if name.startswith("auto_seam_uv_equalizer/") and name.endswith(".py")}
        _verify_modern_uv_api(addon_sources)
        _verify_percentage_facade_routing(addon_sources)
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
