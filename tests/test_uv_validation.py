"""Regression tests for immutable UV quality analysis."""

import importlib.util
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "auto_seam_uv_equalizer" / "uv_validation.py"
spec = importlib.util.spec_from_file_location("uv_validation_test", MODULE)
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


def triangle(uv=((0, 0), (1, 0), (0, 1)), world=((0, 0, 0), (1, 0, 0), (0, 1, 0)), face=0):
    return validation.UVTriangleSnapshot(face, (0, 1, 2), (0, 1, 2), uv, world)


@pytest.mark.parametrize("scale", (0.25, 1.0, 2.0))
def test_uniform_uv_scale_is_stretch_invariant(scale):
    uv = tuple((x * scale, y * scale) for x, y in ((0, 0), (1, 0), (0, 1)))
    result = validation.validate_snapshot((triangle(uv=uv),))
    assert result["average_stretch"] == pytest.approx(1.0)
    assert result["max_stretch"] == pytest.approx(1.0)


@pytest.mark.parametrize("scale", (0.25, 1.0, 4.0))
def test_uniform_world_scale_is_stretch_invariant(scale):
    world = tuple((x * scale, y * scale, z * scale)
                  for x, y, z in ((0, 0, 0), (1, 0, 0), (0, 1, 0)))
    result = validation.validate_snapshot((triangle(world=world),))
    assert result["average_stretch"] == pytest.approx(1.0)


def test_anisotropic_uv_scale_increases_stretch():
    result = validation.validate_snapshot((triangle(uv=((0, 0), (2, 0), (0, 1))),))
    assert result["average_stretch"] == pytest.approx(2.0)
    assert result["average_stretch"] > validation.validate_snapshot((triangle(),))["average_stretch"]


def test_over_threshold_stretch_reports_its_face_for_selection():
    result = validation.validate_snapshot(
        (triangle(uv=((0, 0), (3, 0), (0, 1)), face=12),),
        stretch_threshold=2.0,
    )
    assert result["stretched"] == {12}
    assert result["problem_count"] == 1


def test_flipped_and_zero_triangles_are_detected_without_nonfinite_metrics():
    snapshot = (
        triangle(uv=((0, 0), (0, 1), (1, 0)), face=3),
        triangle(uv=((0, 0), (1, 0), (2, 0)), face=7),
    )
    result = validation.validate_snapshot(snapshot)
    assert result["flipped"] == {3}
    assert result["zero"] == {7}
    assert result["average_stretch"] == pytest.approx(1.0)
    assert result["summed_uv_area"] == result["coverage"] == pytest.approx(0.5)


class _Collection:
    def __init__(self, values):
        self._values = values

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        return self._values[index]


class _Mesh:
    def __init__(self, loop_count, uv_count):
        self.loops = [object()] * loop_count
        self.uv_layers = type("UVLayers", (), {})()
        self.uv_layers.active = type("UVLayer", (), {})()
        self.uv_layers.active.uv = _Collection([object()] * uv_count)
        self.loop_triangles = ()

    def calc_loop_triangles(self):
        pass


def test_uv_collection_invariant_raises_validation_error_not_index_error():
    obj = type("Object", (), {"mode": "OBJECT", "data": _Mesh(3, 0)})()
    with pytest.raises(validation.UVValidationError, match="not synchronized"):
        validation.build_uv_triangle_snapshot(obj)


def test_edit_mode_sync_happens_before_mesh_and_uv_are_acquired():
    stale, current = _Mesh(3, 0), _Mesh(3, 3)

    class Object:
        mode = "EDIT"
        matrix_world = None

        def __init__(self):
            self._mesh = stale
            self.synced = False

        @property
        def data(self):
            return self._mesh

        def update_from_editmode(self):
            self._mesh = current
            self.synced = True
            return True

    obj = Object()
    mesh, uv = validation.prepare_validation_mesh(obj)
    assert obj.synced
    assert mesh is current
    assert uv is current.uv_layers.active


def test_failed_edit_mode_sync_has_explicit_error():
    obj = type("Object", (), {
        "mode": "EDIT", "data": _Mesh(3, 3),
        "update_from_editmode": lambda self: False,
    })()
    with pytest.raises(validation.UVValidationError, match="Could not synchronize"):
        validation.prepare_validation_mesh(obj)


class _OverlapObject:
    def __init__(self, name):
        self.name = name


def _record(name, face, points):
    xs, ys = zip(*points)
    return validation.TriangleRecord(
        _OverlapObject(name), face, points,
        (min(xs), min(ys), max(xs), max(ys)),
    )


def test_overlap_classifies_exact_stack_and_partial_intersection():
    triangle_a = ((0, 0), (1, 0), (0, 1))
    records = [_record("A", 0, triangle_a), _record("B", 0, triangle_a),
               _record("C", 0, ((.25, .25), (1.25, .25), (.25, 1.25)))]
    result = validation.find_overlaps(records, 1e-9, 1e-9)
    assert result.exact_pair_count == 1
    assert result.exact_stacks == {("A", 0), ("B", 0)}
    assert result.partial_pair_count == 2
    assert ("C", 0) in result.partial_overlaps


def test_overlap_ignores_edge_contact_and_honors_across_objects():
    records = [_record("A", 0, ((0, 0), (1, 0), (0, 1))),
               _record("B", 0, ((1, 0), (2, 0), (1, 1)))]
    assert validation.find_overlaps(records, 1e-9, 1e-9).partial_pair_count == 0
    stacked = [_record("A", 0, records[0].coordinates),
               _record("B", 0, records[0].coordinates)]
    assert validation.find_overlaps(stacked, 1e-9, 1e-9, False).exact_pair_count == 0
