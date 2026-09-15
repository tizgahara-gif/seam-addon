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
