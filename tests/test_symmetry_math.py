import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1] / "auto_seam_uv_equalizer"
spec = importlib.util.spec_from_file_location("symmetry_pure", ROOT / "symmetry.py")
symmetry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(symmetry)


def mirrored_quad_data(axis=0):
    coordinates = [(-1, 0, 0), (-1, 1, 0), (-1, 1, 1), (-1, 0, 1),
                   (1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0),
             (4, 5), (5, 6), (6, 7), (7, 4)]
    return coordinates, edges, [(0, 1, 2, 3), (4, 5, 6, 7)]


def test_neighbor_hash_cell_is_searched():
    coordinates = [(-0.99996, 0, 0), (1.00003, 0, 0)]
    mapping, ambiguous = symmetry.build_unique_vertex_mirror(coordinates, 0, 0.0001)
    assert mapping == {0: 1, 1: 0}
    assert ambiguous == 0


def test_ambiguous_vertex_is_rejected():
    coordinates, edges, faces = mirrored_quad_data()
    coordinates.append((1.00001, 0, 0))
    try:
        symmetry.build_symmetry_plan(coordinates, edges, faces, [0], tolerance=0.001)
    except symmetry.SymmetryError as exc:
        assert "ambiguous" in str(exc)
    else:
        raise AssertionError("ambiguous symmetry accepted")


def test_face_edge_and_loop_pair_plan():
    coordinates, edges, faces = mirrored_quad_data()
    plan = symmetry.build_symmetry_plan(coordinates, edges, faces, [0])
    assert plan.face_pairs == {0: 1}
    assert len(plan.edge_pairs) == 4
    assert dict(plan.loop_pairs) == {0: 4, 1: 7, 2: 6, 3: 5}


def test_overlap_and_separate_transfers():
    source = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)] + [(9, 9)] * 4
    pairs = ((0, 4), (1, 7), (2, 6), (3, 5))
    overlap = symmetry.transferred_uvs(source, pairs)
    assert overlap == {4: (0, 0), 7: (1, 0), 6: (1, 1), 5: (0, 1)}
    separate = symmetry.transferred_uvs(source, pairs, "SEPARATE_MIRRORED", 0.25)
    assert min(uv[0] for uv in separate.values()) == 1.25
    assert max(uv[0] for uv in separate.values()) == 2.25


def test_missing_face_rejected_without_writes():
    coordinates, edges, faces = mirrored_quad_data()
    try:
        symmetry.build_symmetry_plan(coordinates, edges, faces[:1], [0])
    except symmetry.SymmetryError as exc:
        assert "missing mirrored face" in str(exc)
    else:
        raise AssertionError("asymmetric mesh accepted")
