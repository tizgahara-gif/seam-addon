"""Pure regression coverage for chart-analysis cache invalidation."""

import importlib.util
import sys
import types
from collections import namedtuple
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
uv_protection = sys.modules["auto_seam_uv_equalizer.uv_protection"]


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


def _apply_fixture(active_uv=object()):
    edges = [SimpleNamespace(index=0, use_seam=False),
             SimpleNamespace(index=1, use_seam=True)]
    mesh = SimpleNamespace(
        vertices=[object(), object(), object()],
        edges=edges,
        polygons=[object()],
        uv_layers=SimpleNamespace(active=active_uv),
        update=lambda *args, **kwargs: None,
    )
    obj = SimpleNamespace(data=mesh)
    result = SimpleNamespace(
        signature=((None,) * 3, (None,) * 2, (None,)),
        pending_seams={0},
    )
    return obj, result


def test_apply_chart_seams_validates_active_uv_before_any_write(monkeypatch):
    obj, result = _apply_fixture()
    original = tuple(edge.use_seam for edge in obj.data.edges)
    calls = []

    def reject(current_obj):
        calls.append(current_obj)
        raise RuntimeError("inconsistent protection")

    monkeypatch.setattr(seam_detection, "validate_protection_consistency", reject)
    monkeypatch.setattr(
        seam_detection, "protected_edge_indices",
        lambda _mesh: (_ for _ in ()).throw(AssertionError("write preparation ran")),
    )

    try:
        seam_detection.apply_chart_seams(obj, result)
    except RuntimeError as exc:
        assert str(exc) == "inconsistent protection"
    else:
        raise AssertionError("protection inconsistency was not propagated")

    assert calls == [obj]
    assert tuple(edge.use_seam for edge in obj.data.edges) == original


def test_apply_chart_seams_validates_cache_safe_metadata_changes(monkeypatch):
    """Group renumbering is cache-safe, but every commit is still preflighted."""
    obj, result = _apply_fixture()
    calls = []
    monkeypatch.setattr(
        seam_detection, "validate_protection_consistency",
        lambda current_obj: calls.append(current_obj),
    )
    monkeypatch.setattr(seam_detection, "protected_edge_indices", lambda _mesh: set())

    assert seam_detection.apply_chart_seams(obj, result) == 0
    assert calls == [obj]
    assert tuple(edge.use_seam for edge in obj.data.edges) == (True, False)


def test_apply_chart_seams_without_active_uv_skips_uv_validation(monkeypatch):
    obj, result = _apply_fixture(active_uv=None)
    monkeypatch.setattr(
        seam_detection, "validate_protection_consistency",
        lambda _obj: (_ for _ in ()).throw(AssertionError("unexpected validation")),
    )
    monkeypatch.setattr(seam_detection, "protected_edge_indices", lambda _mesh: set())

    seam_detection.apply_chart_seams(obj, result)


def _protection_attribute(values):
    item = namedtuple("AttributeValue", "value")
    return SimpleNamespace(
        domain="FACE", data_type="INT", data=[item(value) for value in values])


def test_cached_apply_rejects_each_intra_island_protection_conflict(monkeypatch):
    """Finished groups, Finished state, and Layout Lock are commit barriers."""
    for finished, locked in (((1, 2), (0, 0)),
                             ((1, 0), (0, 0)),
                             ((0, 0), (1, 0))):
        obj, result = _apply_fixture()
        obj.data.attributes = {
            uv_protection.FINISHED_ATTRIBUTE: _protection_attribute(finished),
            uv_protection.LAYOUT_LOCK_ATTRIBUTE: _protection_attribute(locked),
        }
        original = tuple(edge.use_seam for edge in obj.data.edges)
        monkeypatch.setattr(uv_protection, "current_islands", lambda _obj: [(0, 1)])
        monkeypatch.setattr(seam_detection, "validate_protection_consistency",
                            uv_protection.validate_protection_consistency)

        try:
            seam_detection.apply_chart_seams(obj, result)
        except uv_protection.ProtectionError:
            pass
        else:
            raise AssertionError((finished, locked))

        assert tuple(edge.use_seam for edge in obj.data.edges) == original


def test_cached_apply_accepts_consistent_finished_group_renumber(monkeypatch):
    obj, result = _apply_fixture()
    obj.data.attributes = {
        uv_protection.FINISHED_ATTRIBUTE: _protection_attribute((27, 27)),
        uv_protection.LAYOUT_LOCK_ATTRIBUTE: _protection_attribute((0, 0)),
    }
    monkeypatch.setattr(uv_protection, "current_islands", lambda _obj: [(0, 1)])
    monkeypatch.setattr(seam_detection, "validate_protection_consistency",
                        uv_protection.validate_protection_consistency)
    monkeypatch.setattr(seam_detection, "protected_edge_indices", lambda _mesh: set())

    seam_detection.apply_chart_seams(obj, result)
    assert tuple(edge.use_seam for edge in obj.data.edges) == (True, False)
