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
