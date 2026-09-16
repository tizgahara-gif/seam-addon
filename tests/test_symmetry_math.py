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


def test_exact_texture_x_transfer_from_each_half():
    pairs = ((0, 2), (1, 3))
    left = [(0.1, 0.25), (0.5, 0.75), (9, 9), (9, 9)]
    assert symmetry.exact_texture_x_uvs(left, pairs) == {
        2: (0.9, 0.25), 3: (0.5, 0.75),
    }
    right = [(0.6, 0.2), (1.0, 0.8), (9, 9), (9, 9)]
    assert symmetry.exact_texture_x_uvs(right, pairs, "RIGHT_HALF") == {
        2: (0.4, 0.2), 3: (0.0, 0.8),
    }


def test_exact_texture_x_rejects_half_range_and_duplicate_errors():
    for uvs, pairs, message in (
        ([(0.6, 0.5), (9, 9)], ((0, 1),), "texture half"),
        ([(0.2, 1.1), (9, 9)], ((0, 1),), "0-1 UV space"),
        ([(0.2, 0.5), (9, 9)], ((0, 0),), "duplication"),
        ([(0.2, 0.5), (9, 9)], ((0, 3),), "out of range"),
    ):
        try:
            symmetry.exact_texture_x_uvs(uvs, pairs)
        except symmetry.SymmetryError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid exact Texture-X transfer accepted")


def test_selected_faces_expand_to_one_complete_uv_island():
    _coordinates, _edges, faces = mirrored_quad_data()
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1),
           (2, 0), (2, 1), (3, 1), (3, 0)]
    assert symmetry.collect_selected_source_uv_island(faces, uvs, {0}) == {0}
    try:
        symmetry.collect_selected_source_uv_island(faces, uvs, {0, 1})
    except symmetry.SymmetryError as exc:
        assert str(exc) == "Exactly one source UV island must be selected."
    else:
        raise AssertionError("multiple selected UV islands accepted")


def test_mirrored_island_plan_copies_exact_uvs_and_both_seam_states():
    coordinates, edges, faces = mirrored_quad_data()
    source_uvs = [(0.1, 0.2), (0.4, 0.2), (0.4, 0.7), (0.1, 0.7)]
    uvs = source_uvs + [(8.0, 8.0)] * 4
    plan = symmetry.plan_mirrored_island_sync(
        coordinates, edges, faces, {0},
        [True, False, True, False, False, True, False, True], uvs)
    assert plan.seam_writes == {7: True, 6: False, 5: True, 4: False}
    assert plan.uv_writes == {
        4: (0.1, 0.2), 7: (0.4, 0.2),
        6: (0.4, 0.7), 5: (0.1, 0.7),
    }
    assert uvs[4:] == [(8.0, 8.0)] * 4  # Planning is mutation-free.


def test_mirrored_island_loop_mapping_uses_vertices_not_polygon_winding():
    coordinates, edges, faces = mirrored_quad_data()
    plan = symmetry.plan_mirrored_island_sync(
        coordinates, edges, faces, {0}, [False] * 8,
        [(0, 0), (1, 0), (1, 1), (0, 1)] + [(9, 9)] * 4)
    assert plan.symmetry.loop_pairs == ((0, 4), (1, 7), (2, 6), (3, 5))


def test_mirrored_island_rejects_cross_plane_and_missing_topology_without_writes():
    coordinates, edges, faces = mirrored_quad_data()
    seams = [False] * len(edges)
    uvs = [(0, 0)] * 8
    before = (list(seams), list(uvs))
    crossing = list(coordinates)
    crossing[0] = (0.5, 0, 0)
    for args, message in (
        ((crossing, edges, faces), "crosses the mesh symmetry plane"),
        ((coordinates, edges[:4], faces[:1]), "mirrored face"),
    ):
        try:
            symmetry.plan_mirrored_island_sync(
                *args, {0}, seams[:len(args[1])], uvs[:sum(map(len, args[2]))])
        except symmetry.SymmetryError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("invalid mirrored topology accepted")
    assert before == (seams, uvs)
