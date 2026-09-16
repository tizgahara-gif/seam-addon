"""Source-level UI/operator/backend routing contracts (Blender-free)."""

import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / "auto_seam_uv_equalizer"


def _source(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_chart_signature_covers_every_analysis_setting():
    source = _source("seam_detection.py")
    required = {
        "seam_preset", "max_chart_distortion", "seam_count_penalty",
        "seam_minimum_spacing", "straightness_bias", "preserve_existing_seams",
        "material_boundary", "curvature_bias", "weight_material",
        "seam_search_radius", "chart_refinement_iterations", "character_front_axis",
        "use_professional_garment_prior", "mesh_symmetry_axis",
        "mesh_symmetry_tolerance", "use_distortion_guided_candidates",
        "use_edge_loop_completion",
    }
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "analysis_signature")
    literals = {node.value for node in ast.walk(function)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert required <= literals


def test_chart_operators_share_processing_policy_and_revalidate_cache():
    source = _source("operators.py")
    tree = ast.parse(source)
    for class_name in ("AUTOSEAMUV_OT_analyze_seams", "AUTOSEAMUV_OT_generate_seams"):
        node = next(item for item in tree.body
                    if isinstance(item, ast.ClassDef) and item.name == class_name)
        calls = {call.func.id for call in ast.walk(node)
                 if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
        assert "_objects_for_processing" in calls
    assert "result.signature != analysis_signature(obj, settings)" in source


def test_ui_contract_exposes_routed_setting_families():
    ui = _source("ui.py")
    # Representative displayed properties from every public routing family.
    for setting in (
        "angle_threshold", "seam_preset", "unwrap_method",
        "weighted_density_influence", "pack_margin", "atlas_uv_source",
        "mesh_symmetry_axis", "check_overlap_across_objects",
    ):
        assert f'prop(settings, "{setting}"' in ui
    assert "selected_face_seeds_by_mesh" in ui
    assert 'text="Named UV Settings"' in ui


def test_standard_pack_routing_contract_is_unchanged():
    source = _source("uv_pack.py")
    for argument in ("margin", "rotate", "rotate_method", "margin_method",
                     "shape_method", "pin", "pin_method", "merge_overlap",
                     "udim_source"):
        assert f'"{argument}"' in source


def test_weighted_rotation_enum_ui_and_backend_contract():
    properties = _source("properties.py")
    ui = _source("ui.py")
    operators = _source("operators.py")
    backend = _source("weighted_layout.py")
    assert 'weighted_rotation_mode: EnumProperty' in properties
    for identifier in ('"NONE"', '"STEP_90"', '"STEP_15"'):
        assert identifier in properties
    assert 'prop(settings, "weighted_rotation_mode", text="Island Rotation")' in ui
    assert 'prop(settings, "weighted_allow_rotation"' not in ui
    assert "rotation_steps_for_mode(settings.weighted_rotation_mode)" in operators
    assert '"NONE": (0,)' in backend and '"STEP_90": (0, 6)' in backend
    assert '"STEP_15": tuple(range(12))' in backend


def test_weighted_rotation_legacy_migration_is_idempotent_by_key():
    properties = _source("properties.py")
    assert '"weighted_rotation_mode" not in keys' in properties
    assert '"weighted_allow_rotation" in keys' in properties
    assert '"STEP_90" if settings.weighted_allow_rotation else "NONE"' in properties
