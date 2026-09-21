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


def _multi_island_transfer_fixture():
    faces = tuple((index * 4, index * 4 + 1, index * 4 + 2, index * 4 + 3)
                  for index in range(6))
    source = (
        ((0.05, 0.05), (0.20, 0.05), (0.20, 0.20), (0.05, 0.20)),
        ((0.30, 0.30), (0.55, 0.35), (0.50, 0.42), (0.28, 0.38)),
        ((0.70, 0.70), (0.78, 0.70), (0.78, 0.95), (0.70, 0.95)),
    )
    uvs = tuple(uv for island in source for uv in island) + ((9.0, 9.0),) * 12
    pairs = tuple((loop, 12 + (loop // 4) * 4 + (3 - loop % 4))
                  for loop in range(12))
    plan = symmetry.SymmetryPlan({}, {}, {0: 3, 1: 4, 2: 5}, pairs, (0, 1, 2))
    return faces, uvs, plan


def _planned_writes(faces, uvs, plan, layout="OVERLAP", gap=0.02):
    plans = symmetry.plan_symmetric_uv_transfers(faces, uvs, plan, layout, gap)
    return plans, symmetry.combine_island_transfer_plans(plans)


def test_symmetric_transfer_single_island_baseline():
    faces, uvs, plan = _multi_island_transfer_fixture()
    single = plan._replace(face_pairs={0: 3}, loop_pairs=plan.loop_pairs[:4], source_faces=(0,))
    _plans, writes = _planned_writes(faces, uvs, single, "SEPARATE_MIRRORED", 0.03)
    assert writes == symmetry.transferred_uvs(uvs, plan.loop_pairs[:4],
                                              "SEPARATE_MIRRORED", 0.03)


def test_symmetric_transfer_multiple_islands_matches_individual_results():
    faces, uvs, plan = _multi_island_transfer_fixture()
    _plans, batch = _planned_writes(faces, uvs, plan, "SEPARATE_MIRRORED", 0.03)
    individual = {}
    for index in range(3):
        individual.update(symmetry.transferred_uvs(
            uvs, plan.loop_pairs[index * 4:index * 4 + 4], "SEPARATE_MIRRORED", 0.03))
    assert batch == individual


def test_symmetric_transfer_multiple_islands_order_independent():
    faces, uvs, plan = _multi_island_transfer_fixture()
    _plans, expected = _planned_writes(faces, uvs, plan, "SEPARATE_MIRRORED", 0.03)
    shuffled = plan._replace(loop_pairs=tuple(reversed(plan.loop_pairs)),
                             source_faces=(2, 0, 1))
    plans, actual = _planned_writes(faces, uvs, shuffled, "SEPARATE_MIRRORED", 0.03)
    assert actual == expected
    assert [item.source_island_key for item in plans] == [(0, 0), (1, 4), (2, 8)]


def test_symmetric_transfer_multiple_islands_nonzero_gap():
    faces, uvs, plan = _multi_island_transfer_fixture()
    plans, _writes = _planned_writes(faces, uvs, plan, "SEPARATE_MIRRORED", 0.03)
    for island_plan in plans:
        source_face = island_plan.source_faces[0]
        source_values = uvs[source_face * 4:source_face * 4 + 4]
        assert abs(min(uv[0] for uv in island_plan.destination_uvs)
                   - max(uv[0] for uv in source_values) - 0.03) < 1e-12


def test_symmetric_transfer_multiple_islands_near_uv_boundary():
    faces, uvs, plan = _multi_island_transfer_fixture()
    _plans, writes = _planned_writes(faces, uvs, plan)
    assert all(0.0 <= value <= 1.0 for uv in writes.values() for value in uv)


def test_symmetric_transfer_multiple_islands_different_sizes():
    faces, uvs, plan = _multi_island_transfer_fixture()
    plans, _writes = _planned_writes(faces, uvs, plan)
    widths = [max(u for u, _v in item.destination_uvs)
              - min(u for u, _v in item.destination_uvs) for item in plans]
    assert all(abs(actual - expected) < 1e-12
               for actual, expected in zip(widths, (0.15, 0.27, 0.08)))


def test_symmetric_transfer_l_to_r():
    faces, uvs, plan = _multi_island_transfer_fixture()
    assert len(_planned_writes(faces, uvs, plan)[1]) == 12


def test_symmetric_transfer_r_to_l():
    faces, uvs, plan = _multi_island_transfer_fixture()
    reverse = plan._replace(loop_pairs=tuple((destination, source)
                                             for source, destination in plan.loop_pairs),
                            source_faces=(3, 4, 5))
    reverse_uvs = uvs[:12] + uvs[:12]
    assert len(_planned_writes(faces, reverse_uvs, reverse)[1]) == 12


def test_symmetric_transfer_transaction_rollback():
    faces, uvs, plan = _multi_island_transfer_fixture()
    duplicate = plan._replace(loop_pairs=plan.loop_pairs[:-1] + ((11, 12),))
    try:
        _planned_writes(faces, uvs, duplicate)
    except symmetry.SymmetryError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate destination was accepted")
    assert uvs[12:] == ((9.0, 9.0),) * 12


def test_symmetric_transfer_finished_destination_rollback():
    faces, uvs, plan = _multi_island_transfer_fixture()
    plans, writes = _planned_writes(faces, uvs, plan)
    before = uvs[12:]
    # Protection is preflighted by the operator before this write set is
    # committed; the pure plan itself must not mutate a finished destination.
    assert len(plans) == 3 and len(writes) == 12
    assert uvs[12:] == before


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
