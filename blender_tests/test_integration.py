"""Blender 5.1 runtime/registration and core-workflow smoke tests."""
import pathlib
import sys
import unittest

import bpy

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import auto_seam_uv_equalizer as addon


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
                     "detect_ring_strip", "unwrap_ring_strip", "mirror_seams",
                     "validate_symmetry", "transfer_symmetric_uv"):
            self.assertTrue(hasattr(bpy.ops.autoseamuv, name), name)

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
            self.assertEqual(tuple(layer.uv[destination_loop].vector),
                             source_uvs[source_loop])
        settings.symmetry_layout = "SEPARATE_MIRRORED"
        settings.symmetry_island_gap = 0.25
        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})

    def test_selected_symmetric_transfer_preserves_unselected_region_uvs(self):
        obj = mesh_object(
            "SymmetricWithThirdRegion",
            [(-1,0,0),(-1,1,0),(-1,1,1),(-1,0,1),
             (1,0,0),(1,0,1),(1,1,1),(1,1,0),
             (3,2,0),(4,2,0),(4,3,0),(3,3,0)],
            [(0,1,2,3),(4,5,6,7),(8,9,10,11)],
        )
        layer = obj.data.uv_layers.new(name="UVMap")
        initial_uvs = (
            (0.1,0.2),(0.3,0.2),(0.3,0.4),(0.1,0.4),
            (0.6,0.6),(0.7,0.6),(0.7,0.7),(0.6,0.7),
            (0.11,0.81),(0.29,0.83),(0.31,0.97),(0.13,0.99),
        )
        for index, uv in enumerate(initial_uvs):
            layer.uv[index].vector = uv

        for polygon in obj.data.polygons:
            polygon.select = False
        obj.data.polygons[0].select = True
        settings = bpy.context.scene.autoseamuv_settings
        settings.symmetry_scope = "SELECTED"
        settings.symmetry_direction = "NEGATIVE_TO_POSITIVE"
        settings.symmetry_layout = "OVERLAP"
        third_region_loops = tuple(obj.data.polygons[2].loop_indices)
        before = tuple(tuple(layer.uv[index].vector) for index in third_region_loops)

        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})

        after = tuple(tuple(layer.uv[index].vector) for index in third_region_loops)
        self.assertEqual(after, before)


suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
