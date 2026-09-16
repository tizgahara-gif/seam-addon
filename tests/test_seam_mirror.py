import importlib.util
from pathlib import Path


MODULE = Path(__file__).parents[1] / "auto_seam_uv_equalizer" / "seam_mirror.py"
spec = importlib.util.spec_from_file_location("seam_mirror_pure", MODULE)
seam_mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seam_mirror)


def plan(states, direction="POSITIVE", selected=(), mapping=None, midpoints=None):
    mapping = mapping or {0: 1, 1: 0}
    midpoints = midpoints or {0: 1.0, 1: -1.0}
    return seam_mirror.seam_state_assignments(
        mapping, states, midpoints, direction, 0.001, selected,
    )


def test_positive_copies_on_and_off_without_reverse_flow():
    assert plan({0: True, 1: False}) == ({1: True}, 0)
    assert plan({0: False, 1: True}) == ({1: False}, 0)


def test_negative_copies_only_negative_source():
    assert plan({0: True, 1: False}, "NEGATIVE") == ({0: False}, 0)


def test_selected_on_and_off_are_both_authoritative():
    assert plan({0: True, 1: False}, "SELECTED", {0}) == ({1: True}, 0)
    assert plan({0: True, 1: False}, "SELECTED", {1}) == ({0: False}, 0)


def test_bidirectional_mapping_uses_snapshot_and_processes_pair_once():
    assignments, conflicts = plan({0: True, 1: False})
    assert assignments == {1: True}
    assert conflicts == 0


def test_conflicting_selected_pair_is_skipped():
    assert plan({0: True, 1: False}, "SELECTED", {0, 1}) == ({}, 1)


def test_equal_selected_pair_is_not_a_conflict():
    assert plan({0: True, 1: True}, "SELECTED", {0, 1}) == ({}, 0)


def test_center_self_pair_is_noop():
    assert plan({0: True}, mapping={0: 0}, midpoints={0: 0.0}) == ({}, 0)
