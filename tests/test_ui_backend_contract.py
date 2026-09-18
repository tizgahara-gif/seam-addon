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
    assert 'text="UV Map"' in ui


def test_collapsed_architecture_keeps_advanced_controls_reachable():
    properties = _source("properties.py")
    ui = _source("ui.py")
    sections = {
        "show_processing_options", "show_seam_advanced", "show_garment_prior",
        "show_seam_assist", "show_unwrap_advanced", "show_post_unwrap",
        "show_ring_strip", "show_incremental_layout", "show_shared_atlas",
        "show_standard_pack", "show_atlas_settings", "show_exact_texture_x",
        "show_island_transform", "show_validation_settings",
    }
    for name in sections:
        assert f'{name}: BoolProperty' in properties
        assert f'prop(settings, "{name}"' in ui
    assert properties.count("default=False") >= len(sections)


def test_main_stages_have_independent_presentation_only_disclosures():
    properties = _source("properties.py")
    ui = _source("ui.py")
    defaults = {
        "show_stage_seam": "True",
        "show_stage_unwrap": "True",
        "show_stage_layout": "True",
        "show_stage_symmetry": "False",
        "show_stage_validation": "False",
    }
    for index, (name, default) in enumerate(defaults.items(), 1):
        assert f'{name}: BoolProperty(name="{index}.' in properties
        assert f'default={default})' in properties.split(f'{name}: BoolProperty', 1)[1].splitlines()[0]
        assert f'"{name}"' in ui
    assert 'icon="TRIA_DOWN" if expanded else "TRIA_RIGHT"' in ui
    assert "if not _stage_header" in ui
    for backend in ("operators.py", "seam_detection.py", "weighted_layout.py"):
        source = _source(backend)
        assert not any(name in source for name in defaults)


def test_helper_comments_gate_only_explanatory_copy():
    properties = _source("properties.py")
    ui = _source("ui.py")
    assert 'show_helper_comments: BoolProperty(name="Show Helper Comments", default=True)' in properties
    assert 'status.prop(settings, "show_helper_comments")' in ui
    assert "if settings.show_helper_comments:" in ui
    assert '_helper_comment(shared_box, settings, "All selected objects share one weighted atlas.")' in ui
    # Safety and contract state bypass the optional helper.
    for text in (
        "No active UV map.",
        "Select at least one face to seed UV islands.",
        "Pack Islands cannot preserve UV Protection.",
        "Atlas Pack cannot preserve UV Protection",
    ):
        assert text in ui
        assert f'_helper_comment' not in next(
            line for line in ui.splitlines() if text in line
        )
    assert '_error(status, "No active UV map.")' in ui
    for status in ("Target: Selected Objects", "Active UV: %s", "Scope: Selected UV Islands"):
        assert status in ui


def test_public_operator_buttons_have_one_primary_location():
    ui = _source("ui.py")
    tree = ast.parse(ui)
    ids = [arg.value for node in ast.walk(tree) if isinstance(node, ast.Call)
           and isinstance(node.func, ast.Attribute) and node.func.attr == "operator"
           and node.args and isinstance(node.args[0], ast.Constant)
           for arg in node.args[:1]]
    assert len(ids) == len(set(ids)), "duplicate public operator button"


def test_normalized_uv_distances_use_ui_only_percentage_facades():
    ui = _source("ui.py")
    properties = _source("properties.py")
    for facade in (
        "unwrap_margin_percent", "weighted_padding_uv_percent",
        "pack_margin_percent", "symmetry_island_gap_percent",
    ):
        assert f'prop(settings, "{facade}"' in ui
        assert f"{facade}: FloatProperty" in properties
    assert 'prop(settings, "weighted_padding_uv", text="UV Margin")' not in ui
    assert 'prop(settings, "symmetry_island_gap", text="Island Gap")' not in ui


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
