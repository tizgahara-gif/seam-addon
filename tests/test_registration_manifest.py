"""Static registration-manifest invariants that do not require Blender."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "auto_seam_uv_equalizer"


def _class_names(path: Path, variable: str = "CLASSES") -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets)
    )
    names = []
    for item in assignment.value.elts:
        if isinstance(item, ast.Starred):
            module = item.value.value.id
            names.extend(_class_names(ROOT / f"{module}.py"))
        elif isinstance(item, ast.Name):
            names.append(item.id)
        else:
            names.append(item.attr)
    return names


def test_registration_manifest_has_unique_class_names():
    names = _class_names(ROOT / "__init__.py")
    assert len(names) == len(set(names))
    assert names.count("AUTOSEAMUV_PG_settings") == 1
