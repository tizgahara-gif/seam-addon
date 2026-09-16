"""Blender 5.1 runtime/registration and core-workflow smoke tests."""
import math
import importlib
import pathlib
import sys
import unittest

import bpy
import bmesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import auto_seam_uv_equalizer as addon
from auto_seam_uv_equalizer import operators, weighted_layout
from auto_seam_uv_equalizer.symmetry import build_symmetry_plan
from auto_seam_uv_equalizer.weighted_layout import pack_importance_boxes


def uv_bounds(uvs):
    us, vs = zip(*uvs)
    return min(us), max(us), min(vs), max(vs)


def uv_area(uvs):
    return abs(sum(
        uvs[index][0] * uvs[(index + 1) % len(uvs)][1]
        - uvs[(index + 1) % len(uvs)][0] * uvs[index][1]
        for index in range(len(uvs))
    )) * 0.5


def mesh_object(name, vertices, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces); mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj; obj.select_set(True)
    return obj


def symmetric_clothing_strip(name="GoZ_Clothing", rows=4, columns=8):
    """Create a connected, all-quad, bilaterally symmetric sleeve-like strip."""
    vertices = []
    for row in range(rows):
        radius = 1.0 + (0.12 * row)
        for column in range(columns):
            angle = (2.0 * math.pi * column) / columns
            vertices.append((radius * math.cos(angle), radius * math.sin(angle), row * 0.7))
    faces = []
    for row in range(rows - 1):
        for column in range(columns):
            next_column = (column + 1) % columns
            faces.append((
                row * columns + column,
                row * columns + next_column,
                (row + 1) * columns + next_column,
                (row + 1) * columns + column,
            ))
    return mesh_object(name, vertices, faces)


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        addon.register()

    @classmethod
    def tearDownClass(cls):
        addon.unregister()

    def tearDown(self):
        if bpy.context.object and bpy.context.object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="SELECT"); bpy.ops.object.delete(use_global=False)

    def test_operator_registration(self):
        for name in ("mark_selected_region_boundary", "mark_only", "mark_and_unwrap",
                     "unwrap_only", "weighted_island_layout", "pack_islands", "auto_unwrap_pack",
                     "shared_weighted_atlas",
                     "detect_ring_strip", "unwrap_ring_strip", "mirror_seams",
                     "validate_symmetry", "transfer_symmetric_uv",
                     "transfer_exact_texture_x_symmetry"):
            self.assertTrue(hasattr(bpy.ops.autoseamuv, name), name)

    def test_registration_enable_disable_cycle_is_idempotent(self):
        self.assertIn(addon._on_load_post, bpy.app.handlers.load_post)
        addon.unregister()
        addon.unregister()
        self.assertFalse(hasattr(bpy.types.Scene, "autoseamuv_settings"))
        self.assertNotIn(addon._on_load_post, bpy.app.handlers.load_post)
        self.assertFalse(bpy.app.timers.is_registered(
            addon._deferred_migrate_current_file))
        self.assertTrue(all(getattr(bpy.types, item.__name__, None) is not item
                            for item in addon.CLASSES))
        addon.register()
        addon.unregister()
        addon.register()
        self.assertIs(getattr(bpy.types, "AUTOSEAMUV_PG_settings"),
                      addon.properties.AUTOSEAMUV_PG_settings)

    def test_deferred_and_load_post_migrate_all_scenes_idempotently(self):
        scenes = [bpy.context.scene]
        scenes.extend(bpy.data.scenes.new(f"LegacyMigration{index}")
                      for index in range(2))
        try:
            for index, scene in enumerate(scenes):
                settings = scene.autoseamuv_settings
                settings["margin"] = 0.01 + index * 0.01
                settings["mirror_axis"] = "Y"
                settings["symmetry_tolerance"] = 0.002 + index * 0.001

            self.assertIsNone(addon._deferred_migrate_current_file())
            for index, scene in enumerate(scenes):
                settings = scene.autoseamuv_settings
                self.assertAlmostEqual(settings.unwrap_margin, 0.01 + index * 0.01)
                self.assertAlmostEqual(settings.pack_margin, 0.01 + index * 0.01)
                self.assertEqual(settings.mesh_symmetry_axis, "Y")
                self.assertAlmostEqual(settings.mesh_symmetry_tolerance,
                                       0.002 + index * 0.001)

            # Stored current values win on every later migration invocation.
            scenes[0].autoseamuv_settings.unwrap_margin = 0.25
            addon._on_load_post("")
            self.assertAlmostEqual(
                scenes[0].autoseamuv_settings.unwrap_margin, 0.25)
        finally:
            for scene in scenes[1:]:
                bpy.data.scenes.remove(scene)

    def test_migration_does_not_store_defaults_for_a_fresh_scene(self):
        scene = bpy.data.scenes.new("FreshMigration")
        try:
            settings = scene.autoseamuv_settings
            self.assertEqual(set(settings.keys()), set())
            addon._migrate_loaded_scenes()
            self.assertEqual(set(settings.keys()), set())
        finally:
            bpy.data.scenes.remove(scene)

    def test_registration_replaces_stale_property_group(self):
        addon.unregister()
        stale = type(
            "AUTOSEAMUV_PG_settings",
            (bpy.types.PropertyGroup,),
            {"__module__": "auto_seam_uv_equalizer.stale_test"},
        )
        bpy.utils.register_class(stale)
        # Blender 5.1 must expose the exact object accepted by unregister_class.
        registered = getattr(bpy.types, stale.__name__)
        self.assertIs(registered, stale)
        bpy.types.Scene.autoseamuv_settings = bpy.props.PointerProperty(type=stale)

        addon.register()

        current = addon.properties.AUTOSEAMUV_PG_settings
        self.assertIs(getattr(bpy.types, current.__name__), current)
        scene_property = bpy.types.Scene.bl_rna.properties["autoseamuv_settings"]
        self.assertEqual(scene_property.fixed_type.identifier, current.bl_rna.identifier)

    def test_module_reload_removes_previous_generation_runtime_hooks(self):
        old_handler = addon._on_load_post
        old_timer = addon._deferred_migrate_current_file
        self.assertIn(old_handler, bpy.app.handlers.load_post)

        importlib.reload(addon)
        addon.register()

        self.assertNotIn(old_handler, bpy.app.handlers.load_post)
        self.assertFalse(bpy.app.timers.is_registered(old_timer))
        self.assertIn(addon._on_load_post, bpy.app.handlers.load_post)
        self.assertIs(
            bpy.app.driver_namespace[addon._LIFECYCLE_KEY]["load_handler"],
            addon._on_load_post,
        )

    def test_mirror_seam_edit_bmesh_preserves_selection_and_selected_requires_edit(self):
        obj = mesh_object("Mirror", [(-1,0,0),(-1,1,0),(1,0,0),(1,1,0)],
                          [(0,1,3,2)])
        settings = bpy.context.scene.autoseamuv_settings
        settings.mesh_symmetry_axis = "X"; settings.mesh_symmetry_tolerance = 0.0001
        settings.mirror_direction = "SELECTED"
        self.assertEqual(bpy.ops.autoseamuv.mirror_seams(), {"CANCELLED"})
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data); bm.edges.ensure_lookup_table()
        for edge in bm.edges: edge.select = False; edge.seam = False
        source = next(edge for edge in bm.edges
                      if all(vertex.co.x < 0 for vertex in edge.verts))
        target = next(edge for edge in bm.edges
                      if all(vertex.co.x > 0 for vertex in edge.verts))
        source.select = True; source.seam = True
        selected = {edge.index for edge in bm.edges if edge.select}
        bmesh.update_edit_mesh(obj.data)
        self.assertEqual(bpy.ops.autoseamuv.mirror_seams(), {"FINISHED"})
        bm = bmesh.from_edit_mesh(obj.data); bm.edges.ensure_lookup_table()
        self.assertTrue(bm.edges[target.index].seam)
        self.assertEqual({edge.index for edge in bm.edges if edge.select}, selected)

        # A selected edge with Seam OFF is still an authoritative source.
        bm.edges[source.index].seam = False
        bm.edges[target.index].seam = True
        bmesh.update_edit_mesh(obj.data)
        self.assertEqual(bpy.ops.autoseamuv.mirror_seams(), {"FINISHED"})
        bm = bmesh.from_edit_mesh(obj.data); bm.edges.ensure_lookup_table()
        self.assertFalse(bm.edges[target.index].seam)
        self.assertEqual({edge.index for edge in bm.edges if edge.select}, selected)

        # Differing states on two selected counterparts are conflict-skipped.
        bm.edges[source.index].seam = True
        bm.edges[target.index].seam = False
        bm.edges[target.index].select = True
        bmesh.update_edit_mesh(obj.data)
        self.assertEqual(bpy.ops.autoseamuv.mirror_seams(), {"FINISHED"})
        bm = bmesh.from_edit_mesh(obj.data); bm.edges.ensure_lookup_table()
        self.assertTrue(bm.edges[source.index].seam)
        self.assertFalse(bm.edges[target.index].seam)
        bpy.ops.object.mode_set(mode="OBJECT")
        self.assertFalse(obj.data.edges[target.index].use_seam)

    def test_uv_quality_edit_mode_replaces_problem_face_selection(self):
        obj = mesh_object("Quality", [(0,0,0),(1,0,0),(1,1,0),(0,1,0),
                                      (2,0,0),(3,0,0),(3,1,0),(2,1,0)],
                          [(0,1,2,3), (4,5,6,7)])
        layer = obj.data.uv_layers.new(name="UVMap")
        # Face zero has valid area; face one remains collapsed at (0, 0).
        for index, uv in enumerate(((0,0),(1,0),(1,1),(0,1))):
            layer.uv[index].vector = uv
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data); bm.faces.ensure_lookup_table()
        bm.faces[0].select = True; bm.faces[1].select = False
        bmesh.update_edit_mesh(obj.data)
        self.assertEqual(bpy.ops.autoseamuv.validate_uv(), {"FINISHED"})
        bm = bmesh.from_edit_mesh(obj.data); bm.faces.ensure_lookup_table()
        self.assertEqual({face.index for face in bm.faces if face.select}, {1})

    def test_weighted_selected_uv_islands_expands_partial_face_seed(self):
        obj = mesh_object("IslandScope",
                          [(0,0,0),(1,0,0),(2,0,0),(0,1,0),(1,1,0),(2,1,0),
                           (4,0,0),(5,0,0),(5,1,0),(4,1,0)],
                          [(0,1,4,3), (1,2,5,4), (6,7,8,9)])
        layer = obj.data.uv_layers.new(name="UVMap")
        values = ((2,2),(3,2),(3,3),(2,3), (3,2),(4,2),(4,3),(3,3),
                  (8,8),(9,8),(9,9),(8,9))
        for item, uv in zip(layer.uv, values): item.vector = uv
        untouched = tuple(tuple(layer.uv[index].vector) for index in range(8, 12))
        bpy.ops.object.mode_set(mode="EDIT")
        bm = bmesh.from_edit_mesh(obj.data); bm.faces.ensure_lookup_table()
        for face in bm.faces: face.select = False
        bm.faces[0].select = True
        bmesh.update_edit_mesh(obj.data)
        settings = bpy.context.scene.autoseamuv_settings
        settings.weighted_scope = "SELECTED_FACES"
        settings.weighted_padding_pixels = 0
        self.assertEqual(bpy.ops.autoseamuv.weighted_island_layout(), {"FINISHED"})
        # Both faces in the seeded continuous island moved; the other island did not.
        self.assertTrue(any(tuple(layer.uv[index].vector) != values[index]
                            for index in range(4, 8)))
        self.assertEqual(tuple(tuple(layer.uv[index].vector) for index in range(8, 12)),
                         untouched)
        self.assertEqual({face.index for face in bmesh.from_edit_mesh(obj.data).faces if face.select}, {0})

    def test_weighted_maxrects_headless_regressions(self):
        """Blender 5.1.2 headless coverage for weighted packing primitives."""
        self.assertGreaterEqual(bpy.app.version, (5, 1, 2))
        for aspects, minimum_utilization in (([10.0, 1.0], 0.12),
                                              ([100.0, 1.0], 0.012)):
            rectangles, scale = pack_importance_boxes([4.0, 1.0], aspects)
            self.assertTrue(math.isfinite(scale) and scale > 0.0)
            areas = [(x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in rectangles]
            self.assertAlmostEqual(areas[0] / areas[1], 4.0, places=6)
            self.assertGreater(sum(areas), minimum_utilization)
            self.assertLessEqual(rectangles[0][2], rectangles[1][0] + 1e-9)

    def test_shared_weighted_atlas_area_ratio_left_half_and_no_overlap(self):
        large = mesh_object("SharedLarge", [(0,0,0),(2,0,0),(2,2,0),(0,2,0)],
                            [(0,1,2,3)])
        small = mesh_object("SharedSmall", [(3,0,0),(4,0,0),(4,1,0),(3,1,0)],
                            [(0,1,2,3)])
        for obj in (large, small):
            layer = obj.data.uv_layers.new(name="UVMap")
            for item, uv in zip(layer.uv, ((0,0),(1,0),(1,1),(0,1))):
                item.vector = uv
            obj.select_set(True)
        settings = bpy.context.scene.autoseamuv_settings
        settings.weighted_scope = "WHOLE_OBJECT"
        settings.weighted_density_influence = 0.0
        settings.weighted_scale_mode = "ALLOCATE_BY_IMPORTANCE"
        settings.weighted_target_region = "LEFT_HALF"
        settings.weighted_padding_pixels = 0
        self.assertEqual(bpy.ops.autoseamuv.shared_weighted_atlas(), {"FINISHED"})
        areas, bounds = [], []
        for obj in (large, small):
            uvs = tuple(tuple(item.vector) for item in obj.data.uv_layers.active.uv)
            areas.append(uv_area(uvs)); bounds.append(uv_bounds(uvs))
            self.assertGreaterEqual(bounds[-1][0], -1.0e-7)
            self.assertLessEqual(bounds[-1][1], 0.5 + 1.0e-7)
            self.assertGreaterEqual(bounds[-1][2], -1.0e-7)
            self.assertLessEqual(bounds[-1][3], 1.0 + 1.0e-7)
        self.assertAlmostEqual(areas[0] / areas[1], 4.0, places=5)
        a, b = bounds
        self.assertTrue(a[1] <= b[0] + 1.0e-7 or b[1] <= a[0] + 1.0e-7
                        or a[3] <= b[2] + 1.0e-7 or b[3] <= a[2] + 1.0e-7)

    def test_shared_weighted_atlas_transaction_and_linked_mesh_policy(self):
        first = mesh_object("SharedRollbackA", [(0,0,0),(1,0,0),(1,1,0),(0,1,0)],
                            [(0,1,2,3)])
        second = mesh_object("SharedRollbackB", [(2,0,0),(3,0,0),(3,1,0),(2,1,0)],
                             [(0,1,2,3)])
        for obj in (first, second):
            layer = obj.data.uv_layers.new(name="UVMap")
            for item, uv in zip(layer.uv, ((0,0),(1,0),(1,1),(0,1))): item.vector = uv
            obj.select_set(True)
        before = {obj.name: tuple(tuple(item.vector) for item in obj.data.uv_layers.active.uv)
                  for obj in (first, second)}
        original_apply = weighted_layout.apply_weighted_plan
        weighted_layout.apply_weighted_plan = lambda _pending: (_ for _ in ()).throw(
            RuntimeError("intentional shared rollback fixture"))
        try:
            self.assertEqual(bpy.ops.autoseamuv.shared_weighted_atlas(), {"CANCELLED"})
        finally:
            weighted_layout.apply_weighted_plan = original_apply
        self.assertEqual(before, {
            obj.name: tuple(tuple(item.vector) for item in obj.data.uv_layers.active.uv)
            for obj in (first, second)})

        linked = bpy.data.objects.new("SharedLinked", first.data)
        bpy.context.collection.objects.link(linked); linked.select_set(True)
        settings = bpy.context.scene.autoseamuv_settings
        settings.process_shared_mesh_once = False
        self.assertEqual(bpy.ops.autoseamuv.shared_weighted_atlas(), {"CANCELLED"})
        settings.process_shared_mesh_once = True
        self.assertEqual(bpy.ops.autoseamuv.shared_weighted_atlas(), {"FINISHED"})

    def test_weighted_layout_and_pack_preserve_mesh_and_edit_selection(self):
        obj = mesh_object(
            "IndependentUV",
            [(0,0,0),(1,0,0),(1,1,0),(0,1,0), (3,0,0),(5,0,0),(5,1,0),(3,1,0)],
            [(0,1,2,3), (4,5,6,7)],
        )
        layer = obj.data.uv_layers.new(name="ExistingUV")
        for index, uv in enumerate(((2,2),(3,2),(3,3),(2,3), (5,5),(7,5),(7,6),(5,6))):
            layer.uv[index].vector = uv
        topology = (len(obj.data.vertices), len(obj.data.edges), len(obj.data.polygons))
        seams = tuple(edge.use_seam for edge in obj.data.edges)
        island_sizes = ((1.0, 1.0), (2.0, 1.0))

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (True, True, True)
        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
        for item in (*bm.verts, *bm.edges, *bm.faces):
            item.select = False
        bm.verts[0].select = True; bm.edges[0].select = True; bm.faces[0].select = True
        bmesh.update_edit_mesh(obj.data)
        selection = ({v.index for v in bm.verts if v.select},
                     {e.index for e in bm.edges if e.select},
                     {f.index for f in bm.faces if f.select})

        settings = bpy.context.scene.autoseamuv_settings
        settings.weighted_scale_mode = "PRESERVE_TEXEL_DENSITY"
        settings.weighted_scope = "WHOLE_OBJECT"
        settings.weighted_padding_pixels = 0
        self.assertEqual(bpy.ops.autoseamuv.weighted_island_layout(), {"FINISHED"})
        self.assertEqual(topology, (len(obj.data.vertices), len(obj.data.edges), len(obj.data.polygons)))
        self.assertEqual(seams, tuple(edge.use_seam for edge in obj.data.edges))
        scales = []
        for start, expected in zip((0, 4), island_sizes):
            coords = [tuple(layer.uv[index].vector) for index in range(start, start + 4)]
            bounds = uv_bounds(coords)
            scales.append((bounds[1] - bounds[0]) / expected[0])
            self.assertAlmostEqual((bounds[3] - bounds[2]) / expected[1], scales[-1])
        self.assertAlmostEqual(scales[0], scales[1])

        before_pack = tuple(tuple(item.vector) for item in layer.uv)
        self.assertEqual(bpy.ops.autoseamuv.pack_islands(), {"FINISHED"})
        self.assertNotEqual(before_pack, tuple(tuple(item.vector) for item in layer.uv))
        self.assertEqual(topology, (len(obj.data.vertices), len(obj.data.edges), len(obj.data.polygons)))
        self.assertEqual(seams, tuple(edge.use_seam for edge in obj.data.edges))
        restored = bmesh.from_edit_mesh(obj.data)
        self.assertEqual(selection, ({v.index for v in restored.verts if v.select},
                                     {e.index for e in restored.edges if e.select},
                                     {f.index for f in restored.faces if f.select}))
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), (True, True, True))

    def test_pack_rotation_modes(self):
        obj = mesh_object("PackRotation", [(0,0,0),(1,0,0),(1,1,0),(0,1,0)],
                          [(0,1,2,3)])
        obj.data.uv_layers.new(name="UVMap")
        settings = bpy.context.scene.autoseamuv_settings
        settings.pack_shape_method = "CONVEX"
        settings.pack_margin_method = "FRACTION"
        settings.lock_pinned_islands = False
        settings.merge_overlapping = False
        settings.pack_target = "CLOSEST_UDIM"
        for rotation in ("OFF", "ANY", "CARDINAL"):
            settings.pack_rotation = rotation
            self.assertEqual(bpy.ops.autoseamuv.pack_islands(), {"FINISHED"}, rotation)

    def test_object_mode_layout_actions_restore_component_selection(self):
        obj = mesh_object("ObjectSelection", [(0,0,0),(1,0,0),(1,1,0),(0,1,0),
                                                (2,0,0),(3,0,0),(3,1,0),(2,1,0)],
                          [(0,1,2,3), (4,5,6,7)])
        obj.data.uv_layers.new(name="UVMap")
        bpy.ops.object.mode_set(mode="OBJECT")
        obj.data.vertices[1].select = True
        obj.data.edges[2].select = True
        obj.data.polygons[1].select = True
        expected = ({1}, {2}, {1})
        settings = bpy.context.scene.autoseamuv_settings
        settings.average_islands = False
        settings.atlas_average_island_scale = False
        for operation in (bpy.ops.autoseamuv.unwrap_only,
                          bpy.ops.autoseamuv.pack_islands,
                          bpy.ops.autoseamuv.atlas_pack_selected_objects):
            self.assertEqual(operation(), {"FINISHED"})
            self.assertEqual(expected, (
                {v.index for v in obj.data.vertices if v.select},
                {e.index for e in obj.data.edges if e.select},
                {p.index for p in obj.data.polygons if p.select}))

    def test_layout_preflight_rejects_missing_uv_without_partial_processing(self):
        ready = mesh_object("ReadyUV", [(0,0,0),(1,0,0),(1,1,0),(0,1,0)],
                            [(0,1,2,3)])
        layer = ready.data.uv_layers.new(name="UVMap")
        before = tuple(tuple(item.vector) for item in layer.uv)
        missing = mesh_object("MissingUV", [(2,0,0),(3,0,0),(3,1,0),(2,1,0)],
                              [(0,1,2,3)])
        ready.select_set(True); missing.select_set(True)
        bpy.context.view_layer.objects.active = ready
        self.assertEqual(bpy.ops.autoseamuv.weighted_island_layout(), {"CANCELLED"})
        self.assertEqual(bpy.ops.autoseamuv.pack_islands(), {"CANCELLED"})
        self.assertEqual(before, tuple(tuple(item.vector) for item in layer.uv))

    def test_force_and_protect_require_edit_mode_selected_edges(self):
        obj = mesh_object("Tags", [(0,0,0),(1,0,0),(1,1,0)], [(0,1,2)])
        self.assertFalse(bpy.ops.autoseamuv.force_seam.poll())
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        self.assertEqual(bpy.ops.autoseamuv.force_seam(), {"CANCELLED"})
        bpy.ops.object.mode_set(mode="OBJECT")
        obj.data.edges[1].select = True
        bpy.ops.object.mode_set(mode="EDIT")
        self.assertEqual(bpy.ops.autoseamuv.force_seam(), {"FINISHED"})
        self.assertEqual(bpy.ops.autoseamuv.protect_seam(), {"FINISHED"})
        bpy.ops.object.mode_set(mode="OBJECT")
        self.assertEqual([item.value for item in obj.data.attributes["autoseam_force"].data],
                         [False, True, False])
        self.assertEqual([item.value for item in obj.data.attributes["autoseam_protect"].data],
                         [False, True, False])

    def test_selected_boundary_and_auto_seams(self):
        obj = mesh_object("Cube", [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                                    (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)],
                          [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(4,0,3,7)])
        bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT"); obj.data.polygons[0].select = True
        bpy.ops.object.mode_set(mode="EDIT")
        self.assertEqual(bpy.ops.autoseamuv.mark_selected_region_boundary(), {"FINISHED"})
        original = {p.index for p in obj.data.polygons if p.select}
        for mode in ("CLASSIC", "ADVANCED"):
            bpy.context.scene.autoseamuv_settings.seam_mode = mode
            self.assertEqual(bpy.ops.autoseamuv.mark_only(), {"FINISHED"})
            self.assertEqual({p.index for p in obj.data.polygons if p.select}, original)

    def test_chart_production_actions_use_temporary_unwrap(self):
        obj = mesh_object("ChartCube", [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                                         (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)],
                          [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),
                           (2,6,7,3),(4,0,3,7)])
        settings = bpy.context.scene.autoseamuv_settings
        settings.seam_mode = "ADVANCED"
        settings.seam_count_penalty = 0.0
        for preset in ("ORGANIC", "CYLINDER"):
            settings.seam_preset = preset
            self.assertEqual(bpy.ops.autoseamuv.analyze_seams(), {"FINISHED"})
            self.assertEqual(bpy.ops.autoseamuv.generate_seams(), {"FINISHED"})

        for edge in obj.data.edges:
            edge.use_seam = False
        self.assertEqual(bpy.ops.autoseamuv.generate_seams(), {"FINISHED"})
        generated = {edge.index for edge in obj.data.edges if edge.use_seam}
        for edge in obj.data.edges:
            edge.use_seam = False
        self.assertEqual(bpy.ops.autoseamuv.mark_only(), {"FINISHED"})
        self.assertEqual({edge.index for edge in obj.data.edges if edge.use_seam}, generated)

        for polygon in obj.data.polygons:
            polygon.select = polygon.index in {0, 2}
        bpy.ops.object.mode_set(mode="EDIT")
        self.assertEqual(bpy.ops.autoseamuv.unwrap_selected_faces(), {"FINISHED"})

    def test_generate_seams_rolls_back_all_objects_on_apply_failure(self):
        first = mesh_object("RollbackA", [(0,0,0),(1,0,0),(0,1,0)], [(0,1,2)])
        second = mesh_object("RollbackB", [(2,0,0),(3,0,0),(2,1,0)], [(0,1,2)])
        first.data.edges[0].use_seam = True
        before = {obj.name: tuple(edge.use_seam for edge in obj.data.edges)
                  for obj in (first, second)}
        settings = bpy.context.scene.autoseamuv_settings
        settings.seam_mode = "ADVANCED"
        original_apply = operators.apply_chart_seams
        calls = 0

        def fail_second(obj, result):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("intentional rollback fixture")
            return original_apply(obj, result)

        operators.apply_chart_seams = fail_second
        try:
            self.assertEqual(bpy.ops.autoseamuv.generate_seams(), {"CANCELLED"})
        finally:
            operators.apply_chart_seams = original_apply
        self.assertEqual(before, {obj.name: tuple(edge.use_seam for edge in obj.data.edges)
                                  for obj in (first, second)})

    def test_auto_unwrap_pack_restores_edit_face_selection_and_select_mode(self):
        obj = mesh_object("PackSelection", [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                                             (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)],
                          [(0,1,2,3),(4,7,6,5),(0,4,5,1),(1,5,6,2),(2,6,7,3),(4,0,3,7)])
        bpy.ops.object.mode_set(mode="EDIT")
        original_select_mode = (True, False, True)
        bpy.context.tool_settings.mesh_select_mode = original_select_mode

        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            face.select_set(False)
        for face_index in (0, 2):
            bm.faces[face_index].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        original_faces = {face.index for face in bm.faces if face.select}
        self.assertEqual(original_faces, {0, 2})

        self.assertEqual(bpy.ops.autoseamuv.auto_unwrap_pack(), {"FINISHED"})

        self.assertEqual(bpy.context.mode, "EDIT_MESH")
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), original_select_mode)
        restored_bm = bmesh.from_edit_mesh(obj.data)
        restored_bm.faces.ensure_lookup_table()
        restored_faces = {face.index for face in restored_bm.faces if face.select}
        self.assertEqual(restored_faces, original_faces)

    def test_symmetric_uv_layouts_and_missing_map(self):
        obj = mesh_object("Symmetric", [(-1,0,0),(-1,1,0),(-1,1,1),(-1,0,1),
                                         (1,0,0),(1,0,1),(1,1,1),(1,1,0)],
                          [(0,1,2,3),(4,5,6,7)])
        settings = bpy.context.scene.autoseamuv_settings
        settings.symmetry_scope = "WHOLE"
        self.assertEqual(bpy.ops.autoseamuv.validate_symmetry(), {"FINISHED"})
        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"CANCELLED"})
        layer = obj.data.uv_layers.new(name="UVMap")
        source_coordinates = ((0.125, 0.25), (1.375, 0.25),
                              (1.375, 1.0), (0.125, 1.0))
        for index, uv in enumerate(source_coordinates):
            layer.uv[index].vector = uv
        self.assertEqual(bpy.ops.autoseamuv.validate_symmetry(), {"FINISHED"})
        settings.symmetry_layout = "OVERLAP"
        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})
        corresponding_loops = ((0,4),(1,7),(2,6),(3,5))
        for source_loop, destination_loop in corresponding_loops:
            self.assertAlmostEqual(layer.uv[source_loop].vector.x,
                                   layer.uv[destination_loop].vector.x)
            self.assertAlmostEqual(layer.uv[source_loop].vector.y,
                                   layer.uv[destination_loop].vector.y)
        settings.symmetry_layout = "SEPARATE_MIRRORED"
        settings.symmetry_island_gap = 0.25
        source_before_separate = tuple(
            tuple(layer.uv[loop_index].vector) for loop_index in range(4)
        )
        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})
        source_after_separate = tuple(
            tuple(layer.uv[loop_index].vector) for loop_index in range(4)
        )
        destination_uvs = tuple(
            tuple(layer.uv[loop_index].vector) for loop_index in range(4, 8)
        )
        self.assertEqual(source_after_separate, source_before_separate)
        self.assertAlmostEqual(uv_area(source_after_separate), uv_area(destination_uvs))
        source_min_u, source_max_u, source_min_v, source_max_v = uv_bounds(source_after_separate)
        destination_min_u, destination_max_u, destination_min_v, destination_max_v = uv_bounds(destination_uvs)
        self.assertAlmostEqual(source_max_u - source_min_u,
                               destination_max_u - destination_min_u)
        self.assertAlmostEqual(source_max_v - source_min_v,
                               destination_max_v - destination_min_v)
        self.assertGreaterEqual(destination_min_u - source_max_u,
                                settings.symmetry_island_gap - 1.0e-6)
        mirror_sum = source_min_u + source_max_u + (
            source_max_u - source_min_u + settings.symmetry_island_gap
        )
        for source_loop, destination_loop in corresponding_loops:
            self.assertAlmostEqual(layer.uv[source_loop].vector.x
                                   + layer.uv[destination_loop].vector.x,
                                   mirror_sum)

    def test_symmetric_uv_transfer_restores_edit_mode_face_selection(self):
        obj = mesh_object("SymmetricSelection", [(-1,0,0),(-1,1,0),(-1,1,1),(-1,0,1),
                                                  (1,0,0),(1,0,1),(1,1,1),(1,1,0)],
                          [(0,1,2,3),(4,5,6,7)])
        layer = obj.data.uv_layers.new(name="UVMap")
        for index, uv in enumerate(((0,0),(1,0),(1,1),(0,1))):
            layer.uv[index].vector = uv

        settings = bpy.context.scene.autoseamuv_settings
        settings.mesh_symmetry_axis = "X"
        settings.symmetry_direction = "NEGATIVE_TO_POSITIVE"
        settings.symmetry_scope = "SELECTED"
        settings.symmetry_layout = "OVERLAP"

        bpy.ops.object.mode_set(mode="EDIT")
        original_select_mode = (False, False, True)
        bpy.context.tool_settings.mesh_select_mode = original_select_mode
        bpy.ops.mesh.select_all(action="DESELECT")
        edit_mesh = bmesh.from_edit_mesh(obj.data)
        edit_mesh.faces.ensure_lookup_table()
        edit_mesh.faces[0].select_set(True)
        bmesh.update_edit_mesh(obj.data)
        original_selection = {face.index for face in edit_mesh.faces if face.select}
        self.assertEqual(original_selection, {0})

        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})
        self.assertEqual(bpy.context.mode, "EDIT_MESH")
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         original_select_mode)
        restored_mesh = bmesh.from_edit_mesh(obj.data)
        restored_mesh.faces.ensure_lookup_table()
        restored_selection = {
            face.index for face in restored_mesh.faces if face.select
        }
        self.assertEqual(restored_selection, original_selection)

    def _exact_texture_mesh(self):
        return mesh_object(
            "ExactTextureX",
            [(-1,0,0),(-1,1,0),(-1,1,1),(-1,0,1),
             (1,0,0),(1,0,1),(1,1,1),(1,1,0),
             (3,0,0),(4,0,0),(4,1,0),(3,1,0)],
            [(0,1,2,3),(4,5,6,7),(8,9,10,11)],
        )

    def _prepare_exact_texture_transfer(self, source_uvs):
        obj = self._exact_texture_mesh()
        layer = obj.data.uv_layers.new(name="UVMap")
        initial = tuple(source_uvs) + ((0.02,0.03),) * 4 + ((0.41,0.42),) * 4
        for loop_index, uv in enumerate(initial):
            layer.uv[loop_index].vector = uv
        initial = tuple(tuple(item.vector) for item in layer.uv)
        settings = bpy.context.scene.autoseamuv_settings
        settings.mesh_symmetry_axis = "X"
        settings.symmetry_direction = "NEGATIVE_TO_POSITIVE"
        settings.symmetry_scope = "SELECTED"
        bpy.ops.object.mode_set(mode="EDIT")
        select_mode = (False, False, True)
        bpy.context.tool_settings.mesh_select_mode = select_mode
        bpy.ops.mesh.select_all(action="DESELECT")
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.faces[0].select_set(True)
        bmesh.update_edit_mesh(obj.data)
        return obj, layer, settings, initial, select_mode

    def test_exact_texture_x_left_source_selection_and_unrelated(self):
        source = ((0.10,0.20),(0.30,0.20),(0.30,0.80),(0.10,0.80))
        obj, layer, settings, initial, select_mode = self._prepare_exact_texture_transfer(source)
        settings.texture_source_side = "LEFT_HALF"
        self.assertEqual(bpy.ops.autoseamuv.transfer_exact_texture_x_symmetry(),
                         {"FINISHED"})
        loop_pairs = ((0,4),(1,7),(2,6),(3,5))
        for source_loop, destination_loop in loop_pairs:
            self.assertAlmostEqual(layer.uv[destination_loop].vector.x,
                                   1.0 - layer.uv[source_loop].vector.x)
            self.assertAlmostEqual(layer.uv[destination_loop].vector.y,
                                   layer.uv[source_loop].vector.y)
        self.assertEqual(tuple(tuple(layer.uv[index].vector) for index in range(4)),
                         initial[:4])
        self.assertEqual(tuple(tuple(layer.uv[index].vector) for index in range(8, 12)),
                         initial[8:12])
        self.assertEqual(bpy.context.mode, "EDIT_MESH")
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), select_mode)
        bm = bmesh.from_edit_mesh(obj.data)
        self.assertEqual({face.index for face in bm.faces if face.select}, {0})

    def test_exact_texture_x_center_line_is_valid(self):
        source = ((0.10,0.20),(0.30,0.20),(0.50,0.80),(0.10,0.80))
        _obj, layer, settings, _initial, _select_mode = self._prepare_exact_texture_transfer(source)
        settings.texture_source_side = "LEFT_HALF"
        self.assertEqual(bpy.ops.autoseamuv.transfer_exact_texture_x_symmetry(),
                         {"FINISHED"})
        self.assertAlmostEqual(layer.uv[6].vector.x, 0.5)

    def test_exact_texture_x_right_half(self):
        source = ((0.70,0.20),(0.90,0.20),(0.90,0.80),(0.70,0.80))
        _obj, layer, settings, _initial, _select_mode = self._prepare_exact_texture_transfer(source)
        settings.texture_source_side = "RIGHT_HALF"
        self.assertEqual(bpy.ops.autoseamuv.transfer_exact_texture_x_symmetry(),
                         {"FINISHED"})
        for source_loop, destination_loop in ((0,4),(1,7),(2,6),(3,5)):
            self.assertAlmostEqual(layer.uv[destination_loop].vector.x,
                                   1.0 - source[source_loop][0])
            self.assertAlmostEqual(layer.uv[destination_loop].vector.y,
                                   source[source_loop][1])

    def test_weighted_target_half_then_exact_texture_x_both_directions(self):
        for target, source_side, source in (
            ("LEFT_HALF", "LEFT_HALF", ((2,2),(4,2),(4,3),(2,3))),
            ("RIGHT_HALF", "RIGHT_HALF", ((-2,-2),(0,-2),(0,-1),(-2,-1))),
        ):
            with self.subTest(target=target):
                _obj, layer, settings, initial, select_mode = self._prepare_exact_texture_transfer(source)
                settings.weighted_target_region = target
                settings.weighted_scope = "SELECTED_FACES"
                settings.weighted_scale_mode = "ALLOCATE_BY_IMPORTANCE"
                settings.weighted_padding_pixels = 4
                self.assertEqual(bpy.ops.autoseamuv.weighted_island_layout(), {"FINISHED"})
                minimum = 0.0 if target == "LEFT_HALF" else 0.5
                maximum = 0.5 if target == "LEFT_HALF" else 1.0
                for index in range(4):
                    uv = layer.uv[index].vector
                    self.assertGreaterEqual(uv.x, minimum - 1e-7)
                    self.assertLessEqual(uv.x, maximum + 1e-7)
                    self.assertGreaterEqual(uv.y, -1e-7)
                    self.assertLessEqual(uv.y, 1.0 + 1e-7)
                settings.texture_source_side = source_side
                self.assertEqual(bpy.ops.autoseamuv.transfer_exact_texture_x_symmetry(), {"FINISHED"})
                for source_loop, destination_loop in ((0,4),(1,7),(2,6),(3,5)):
                    self.assertAlmostEqual(layer.uv[source_loop].vector.x
                                           + layer.uv[destination_loop].vector.x, 1.0)
                    self.assertAlmostEqual(layer.uv[source_loop].vector.y,
                                           layer.uv[destination_loop].vector.y)
                self.assertEqual(tuple(tuple(layer.uv[index].vector) for index in range(8, 12)),
                                 initial[8:12])
                self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), select_mode)
                bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.select_all(action="SELECT")
                bpy.ops.object.delete(use_global=False)

    def test_exact_texture_x_rejections_do_not_modify_uvs(self):
        for source in (
            ((0.30,0.20),(0.70,0.20),(0.70,0.80),(0.30,0.80)),
            ((-0.10,0.20),(0.30,0.20),(0.30,0.80),(0.10,0.80)),
            ((0.10,0.20),(0.30,0.20),(0.30,1.10),(0.10,0.80)),
        ):
            with self.subTest(source=source):
                _obj, layer, settings, initial, _select_mode = self._prepare_exact_texture_transfer(source)
                settings.texture_source_side = "LEFT_HALF"
                self.assertEqual(bpy.ops.autoseamuv.transfer_exact_texture_x_symmetry(),
                                 {"CANCELLED"})
                self.assertEqual(tuple(tuple(item.vector) for item in layer.uv), initial)
                bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.select_all(action="SELECT")
                bpy.ops.object.delete(use_global=False)

    def test_symmetric_uv_selected_scope_preserves_unrelated_active_map_region(self):
        obj = mesh_object(
            "SymmetricWithUnrelatedRegion",
            [(-1,0,0),(-1,1,0),(-1,1,1),(-1,0,1),
             (1,0,0),(1,0,1),(1,1,1),(1,1,0),
             (3,0,0),(4,0,0),(4,1,0),(3,1,0)],
            [(0,1,2,3),(4,5,6,7),(8,9,10,11)],
        )
        layer = obj.data.uv_layers.new(name="UVMap")
        initial_uvs = tuple(
            (0.07 * loop_index, 0.11 * loop_index + 0.03)
            for loop_index in range(len(obj.data.loops))
        )
        for loop_index, uv in enumerate(initial_uvs):
            layer.uv[loop_index].vector = uv

        settings = bpy.context.scene.autoseamuv_settings
        settings.mesh_symmetry_axis = "X"
        settings.symmetry_direction = "NEGATIVE_TO_POSITIVE"
        settings.symmetry_scope = "SELECTED"
        settings.symmetry_layout = "OVERLAP"

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="DESELECT")
        edit_mesh = bmesh.from_edit_mesh(obj.data)
        edit_mesh.faces.ensure_lookup_table()
        edit_mesh.faces[0].select_set(True)
        bmesh.update_edit_mesh(obj.data)
        unrelated_before = tuple(
            tuple(layer.uv[loop_index].vector)
            for loop_index in obj.data.polygons[2].loop_indices
        )

        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})

        unrelated_after = tuple(
            tuple(layer.uv[loop_index].vector)
            for loop_index in obj.data.polygons[2].loop_indices
        )
        self.assertEqual(unrelated_after, unrelated_before)

    def test_ring_unwrap_restores_edit_mode_face_selection_and_select_mode(self):
        obj = symmetric_clothing_strip(name="RingSelection")
        settings = bpy.context.scene.autoseamuv_settings
        settings.uv_map_name = "RingUV"
        settings.create_uv_if_missing = True
        settings.ring_seam_mode = "AUTO"

        bpy.ops.object.mode_set(mode="EDIT")
        original_select_mode = (False, False, True)
        bpy.context.tool_settings.mesh_select_mode = original_select_mode
        bpy.ops.mesh.select_all(action="SELECT")
        edit_mesh = bmesh.from_edit_mesh(obj.data)
        edit_mesh.faces.ensure_lookup_table()
        original_selection = {
            face.index for face in edit_mesh.faces if face.select
        }

        self.assertEqual(bpy.ops.autoseamuv.unwrap_ring_strip(), {"FINISHED"})

        self.assertEqual(bpy.context.mode, "EDIT_MESH")
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         original_select_mode)
        restored_mesh = bmesh.from_edit_mesh(obj.data)
        restored_mesh.faces.ensure_lookup_table()
        restored_selection = {
            face.index for face in restored_mesh.faces if face.select
        }
        self.assertEqual(restored_selection, original_selection)

    def _run_goz_symmetric_clothing_workflow(self, unwrap_stage, unwrap_operation):
        """Exercise one GoZ-equivalent workflow without overwriting its unwrap."""
        obj = symmetric_clothing_strip()
        mesh = obj.data
        material_a = bpy.data.materials.new("GoZ Cloth")
        material_b = bpy.data.materials.new("GoZ Trim")
        mesh.materials.append(material_a)
        mesh.materials.append(material_b)
        for polygon in mesh.polygons:
            polygon.material_index = polygon.index % 2

        target = mesh.uv_layers.new(name="UV_Auto")
        untouched = mesh.uv_layers.new(name="GoZ_Source_UV")
        mesh.uv_layers.active = target
        for loop_index, datum in enumerate(untouched.uv):
            datum.vector = ((loop_index % 11) / 13.0, (loop_index % 7) / 9.0)

        topology = (
            tuple(tuple(vertex.co) for vertex in mesh.vertices),
            tuple(tuple(edge.vertices) for edge in mesh.edges),
            tuple(tuple(polygon.vertices) for polygon in mesh.polygons),
        )
        materials = (
            tuple(material.name for material in mesh.materials),
            tuple(polygon.material_index for polygon in mesh.polygons),
        )
        untouched_uv = tuple(tuple(datum.vector) for datum in untouched.uv)

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_mode(type="FACE")
        bpy.ops.mesh.select_all(action="SELECT")
        selected_faces = set(range(len(mesh.polygons)))
        selected_mode = tuple(bpy.context.tool_settings.mesh_select_mode)

        settings = bpy.context.scene.autoseamuv_settings
        settings.uv_map_name = target.name
        settings.ring_seam_mode = "AUTO"
        settings.mesh_symmetry_axis = "X"
        settings.symmetry_direction = "NEGATIVE_TO_POSITIVE"
        settings.symmetry_scope = "SELECTED"
        settings.symmetry_layout = "OVERLAP"

        def assert_invariants(stage):
            self.assertEqual(bpy.context.mode, "EDIT_MESH",
                             f"{stage}: edit mode changed")
            self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                             selected_mode, f"{stage}: select mode changed")
            bm = bmesh.from_edit_mesh(mesh)
            bm.faces.ensure_lookup_table()
            self.assertEqual(
                {face.index for face in bm.faces if face.select}, selected_faces,
                f"{stage}: face selection changed",
            )
            current_topology = (
                tuple(tuple(vertex.co) for vertex in mesh.vertices),
                tuple(tuple(edge.vertices) for edge in mesh.edges),
                tuple(tuple(polygon.vertices) for polygon in mesh.polygons),
            )
            self.assertEqual(current_topology, topology, f"{stage}: mesh topology changed")
            self.assertEqual(
                (tuple(material.name for material in mesh.materials),
                 tuple(polygon.material_index for polygon in mesh.polygons)),
                materials,
                f"{stage}: materials changed",
            )
            self.assertEqual(
                tuple(tuple(datum.vector) for datum in untouched.uv), untouched_uv,
                f"{stage}: non-target UV map changed",
            )
            self.assertEqual(mesh.uv_layers.active.name, target.name,
                             f"{stage}: active UV map changed")

        def run_stage(stage, operation):
            try:
                result = operation()
            except Exception as exc:
                self.fail(f"{stage}: {type(exc).__name__}: {exc}")
            self.assertEqual(result, {"FINISHED"}, f"{stage}: returned {result}")
            assert_invariants(stage)

        run_stage("Selected Region Boundary -> Seam",
                  bpy.ops.autoseamuv.mark_selected_region_boundary)
        run_stage(unwrap_stage, unwrap_operation)
        run_stage("Validate Symmetry", bpy.ops.autoseamuv.validate_symmetry)
        run_stage("Transfer Symmetric UV", bpy.ops.autoseamuv.transfer_symmetric_uv)

        plan = build_symmetry_plan(
            [tuple(vertex.co) for vertex in mesh.vertices],
            [tuple(edge.vertices) for edge in mesh.edges],
            [tuple(face.vertices) for face in mesh.polygons],
            [face for face in selected_faces
             if all(mesh.vertices[vertex].co.x <= settings.mesh_symmetry_tolerance
                    for vertex in mesh.polygons[face].vertices)
             and any(mesh.vertices[vertex].co.x < -settings.mesh_symmetry_tolerance
                     for vertex in mesh.polygons[face].vertices)],
            axis=0,
            source_sign=-1,
            tolerance=settings.mesh_symmetry_tolerance,
        )
        for source_loop, destination_loop in plan.loop_pairs:
            self.assertAlmostEqual(target.uv[source_loop].vector.x,
                                   target.uv[destination_loop].vector.x, places=6)
            self.assertAlmostEqual(target.uv[source_loop].vector.y,
                                   target.uv[destination_loop].vector.y, places=6)

        self.assertTrue(all(
            math.isfinite(component)
            for datum in target.uv
            for component in datum.vector
        ), f"{unwrap_stage}: target UV contains a non-finite coordinate")

    def test_general_goz_symmetric_clothing_workflow_regression(self):
        self._run_goz_symmetric_clothing_workflow(
            "Auto Unwrap / Pack", bpy.ops.autoseamuv.auto_unwrap_pack
        )

    def test_ring_goz_symmetric_clothing_workflow_regression(self):
        self._run_goz_symmetric_clothing_workflow(
            "Ring / Strip Unwrap", bpy.ops.autoseamuv.unwrap_ring_strip
        )


suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
