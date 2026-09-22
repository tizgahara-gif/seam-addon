"""Package registry verification regressions."""

import importlib.util
from pathlib import Path
import zipfile

import pytest


SPEC = importlib.util.spec_from_file_location(
    "verify_package", Path(__file__).parents[1] / "scripts" / "verify_package.py"
)
verify_package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_package)


def make_registry_zip(path, ui_source):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "auto_seam_uv_equalizer/__init__.py",
            "CLASSES = (*operators.CLASSES, *ui.CLASSES)\n",
        )
        archive.writestr("auto_seam_uv_equalizer/operators.py", "CLASSES = ()\n")
        archive.writestr("auto_seam_uv_equalizer/ui.py", ui_source)


def test_classes_registry_ast_accepts_all_definitions(tmp_path):
    package = tmp_path / "valid.zip"
    make_registry_zip(package, "CLASSES = ()\n")
    with zipfile.ZipFile(package) as archive:
        verify_package._verify_classes_registries(archive)


def test_classes_registry_ast_rejects_missing_definition(tmp_path):
    package = tmp_path / "invalid.zip"
    make_registry_zip(package, "# The text ui.CLASSES is not a definition.\n")
    with zipfile.ZipFile(package) as archive:
        with pytest.raises(RuntimeError, match="ui.py has no module-level CLASSES"):
            verify_package._verify_classes_registries(archive)


def test_weighted_layout_backend_ast_requires_current_call_chain():
    source = """
def calculate_weights(): pass
def importance_boxes(): pass
def _maxrects_pack(): pass
def pack_importance_boxes():
    importance_boxes()
    _maxrects_pack()
def collect_weighted_islands(): pass
def apply_weighted_plan(): pass
def plan_weighted_layout():
    calculate_weights()
    pack_importance_boxes()
def weighted_layout_object():
    collect_weighted_islands()
    plan_weighted_layout()
    apply_weighted_plan()
def shared_weighted_layout():
    collect_weighted_islands()
    plan_weighted_layout()
    apply_weighted_plan()
"""
    verify_package._verify_weighted_layout_backend(source)


def test_weighted_layout_backend_ast_rejects_disconnected_packer():
    source = """
def calculate_weights(): pass
def importance_boxes(): pass
def _maxrects_pack(): pass
def pack_importance_boxes(): pass
def collect_weighted_islands(): pass
def apply_weighted_plan(): pass
def plan_weighted_layout(): pass
def weighted_layout_object():
    collect_weighted_islands()
    plan_weighted_layout()
    apply_weighted_plan()
def shared_weighted_layout():
    collect_weighted_islands()
    plan_weighted_layout()
    apply_weighted_plan()
"""
    with pytest.raises(RuntimeError, match="does not call"):
        verify_package._verify_weighted_layout_backend(source)


def test_deprecated_uv_api_is_rejected():
    with pytest.raises(RuntimeError, match="Deprecated UV API"):
        verify_package._verify_modern_uv_api({"addon/bad.py": "uv_layer.data[i].uv"})


def test_blender_5_uv_api_is_accepted():
    verify_package._verify_modern_uv_api({"addon/good.py": "uv_layer.uv[i].vector"})


def test_duplicate_translation_literal_keys_are_rejected():
    source = '_JA_JP = {"Advanced": "A", "Advanced": "B"}\n'
    with pytest.raises(RuntimeError, match="Duplicate translation literal keys"):
        verify_package._verify_translation_keys(source)


def test_unique_translation_literal_keys_are_accepted():
    verify_package._verify_translation_keys('_JA_JP = {"Simple": "S"}\n')


def test_percentage_facades_are_accepted_at_ui_boundary():
    verify_package._verify_percentage_facade_routing({
        "auto_seam_uv_equalizer/properties.py": "weighted_padding_uv_percent",
        "auto_seam_uv_equalizer/ui.py": "weighted_padding_uv_percent",
        "auto_seam_uv_equalizer/percentage_facades.py": "def get_percent(): pass",
        "auto_seam_uv_equalizer/weighted_layout.py": "settings.weighted_padding_uv",
    })


def test_percentage_facades_are_rejected_in_backends():
    with pytest.raises(RuntimeError, match="Backend reads percentage"):
        verify_package._verify_percentage_facade_routing({
            "auto_seam_uv_equalizer/weighted_layout.py":
                "settings.weighted_padding_uv_percent",
        })
