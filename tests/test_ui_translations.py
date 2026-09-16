import ast
from pathlib import Path


ROOT = Path(__file__).parents[1] / "auto_seam_uv_equalizer"


def test_all_literal_ui_text_has_a_japanese_translation():
    ui_tree = ast.parse((ROOT / "ui.py").read_text(encoding="utf-8"))
    visible = {
        keyword.value.value
        for node in ast.walk(ui_tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "text" and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    }
    # Runtime helpers and iface_ templates are not covered by Blender's
    # automatic translation of literal layout text.
    visible |= {
        arg.value
        for node in ast.walk(ui_tree)
        if isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id in {"_warning", "_info", "iface_"}))
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    }
    # Preset descriptions are canonical English dictionary values translated
    # at draw time.
    visible |= {
        value.value for node in ast.walk(ui_tree) if isinstance(node, ast.Dict)
        for value in node.values
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }

    translation_tree = ast.parse((ROOT / "translations.py").read_text(encoding="utf-8"))
    dictionary = next(
        node.value for node in translation_tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_JA_JP"
                for target in node.targets)
    )
    translated = {
        key.value for key in dictionary.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert visible <= translated, f"Missing Japanese UI translations: {sorted(visible - translated)}"


def test_dynamic_warning_translates_template_before_formatting():
    source = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert '_warning(box, "%d selected mesh object(s) have no usable UV map.",' in source
    ui_tree = ast.parse(source)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "iface_" and node.args
                   and isinstance(node.args[0], (ast.BinOp, ast.JoinedStr))
                   for node in ast.walk(ui_tree))

    namespace = {}
    tree = ast.parse((ROOT / "translations.py").read_text(encoding="utf-8"))
    dictionary = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "_JA_JP"
                              for target in node.targets))
    namespace["translations"] = ast.literal_eval(dictionary)
    assert namespace["translations"]["%d selected mesh object(s) have no usable UV map."] % 2 == \
        "2個の選択メッシュオブジェクトに使用可能なUVマップがありません。"


def test_workflow_scope_labels_and_warning_conditions_are_explicit():
    ui = (ROOT / "ui.py").read_text(encoding="utf-8")
    properties = (ROOT / "properties.py").read_text(encoding="utf-8")
    assert 'text="Selected Objects Post-Unwrap"' in ui
    assert 'text="Clear All Tags"' in ui
    assert 'weighted_target_region in {"LEFT_HALF", "RIGHT_HALF"}' in ui
    assert 'weighted_scale_mode == "ALLOCATE_BY_IMPORTANCE"' in ui
    assert '("SELECTED_FACES", "Selected UV Islands"' in properties
