"""Pure regression coverage for chart-analysis cache invalidation."""

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).parents[1] / "auto_seam_uv_equalizer"
package = sys.modules.setdefault(
    "auto_seam_uv_equalizer", types.ModuleType("auto_seam_uv_equalizer"))
package.__path__ = [str(ROOT)]
spec = importlib.util.spec_from_file_location(
    "auto_seam_uv_equalizer.seam_detection", ROOT / "seam_detection.py")
seam_detection = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = seam_detection
spec.loader.exec_module(seam_detection)


def _settings():
    return SimpleNamespace(**{
        name: (True if name in {"use_distortion_guided_candidates",
                                "use_edge_loop_completion"} else name)
        for name in seam_detection.CHART_ANALYSIS_SETTING_NAMES
    })


def test_finished_edge_mask_invalidates_analysis_signature(monkeypatch):
    vertices = [SimpleNamespace(co=(0.0, 0.0, 0.0)),
                SimpleNamespace(co=(1.0, 0.0, 0.0))]
    edges = [SimpleNamespace(index=0, vertices=(0, 1), use_seam=False,
                             use_edge_sharp=False)]
    polygons = [SimpleNamespace(vertices=(0, 1), material_index=0)]
    mesh = SimpleNamespace(vertices=vertices, edges=edges, polygons=polygons)
    obj = SimpleNamespace(data=mesh)
    monkeypatch.setattr(seam_detection, "_bool_edge_attribute",
                        lambda _mesh, _name: [False])
    monkeypatch.setattr(seam_detection, "build_edge_to_faces",
                        lambda _mesh: {0: [0]})
    mask = set()
    monkeypatch.setattr(seam_detection, "protected_edge_indices",
                        lambda _mesh, _edge_faces=None: set(mask))

    unprotected = seam_detection.analysis_signature(obj, _settings())
    mask.add(0)
    protected = seam_detection.analysis_signature(obj, _settings())

    assert unprotected != protected
    assert unprotected[6] == (False,)
    assert protected[6] == (True,)
