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


def _japanese_translations():
    tree = ast.parse((ROOT / "translations.py").read_text(encoding="utf-8"))
    dictionary = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "_JA_JP"
                              for target in node.targets))
    return ast.literal_eval(dictionary)


def test_uv_protection_translation_keys_and_canonical_terms():
    translations = _japanese_translations()
    expected = {
        "UV Protection": "UV保護",
        "Finished": "完成済み",
        "Finished Islands": "完成済みアイランド",
        "Layout Lock": "レイアウト固定",
        "Layout Locked Islands": "レイアウト固定アイランド",
        "Mark Finished": "完成済みに設定",
        "Unmark Finished": "完成済みを解除",
        "Lock Layout": "レイアウトを固定",
        "Unlock Layout": "レイアウト固定を解除",
        "Pack Selected Into Free Space": "選択UVアイランドを空き領域へ配置",
    }
    assert {key: translations.get(key) for key in expected} == expected


def test_uv_protection_dynamic_reports_translate_before_formatting():
    translations = _japanese_translations()
    assert translations["Finished Islands: %d"] % 3 == "完成済みアイランド: 3"
    assert translations["Layout Locked Islands: %d"] % 3 == \
        "レイアウト固定アイランド: 3"
    assert translations["Marked %d UV islands as Finished."] % 3 == \
        "3個のUVアイランドを完成済みに設定しました。"


def test_uv_protection_has_no_forbidden_japanese_wording():
    translations = _japanese_translations()
    protection_sources = (
        "UV Protection", "Finished", "Layout Lock", "Layout Locked",
        "Mark Finished", "Unmark Finished", "Lock Layout", "Unlock Layout",
        "Pack Selected Into Free Space", "Protection state",
    )
    protection_text = "\n".join(
        target for source, target in translations.items()
        if any(term in source for term in protection_sources)
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    # Escapes keep the prohibited spellings out of source scans themselves.
    forbidden_terms = (
        "\u30ec\u30a4\u30a2\u30a6\u30c8\u30ed\u30c3\u30af",
        "\u5b8c\u4e86\u6e08\u307f",
        "\u4ed5\u4e0a\u3052\u6e08\u307f",
    )
    for forbidden in forbidden_terms:
        assert forbidden not in protection_text
        assert forbidden not in readme
