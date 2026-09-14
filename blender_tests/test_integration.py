"""Blender 5.1 runtime/registration and core-workflow smoke tests."""
import math
import pathlib
import sys
import unittest

import bpy
import bmesh

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import auto_seam_uv_equalizer as addon


def mesh_object(name, vertices, faces):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces); mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj; obj.select_set(True)
    return obj


def ring_object(name="Ring", rows=4, columns=8):
    vertices = [
        (math.cos(2.0 * math.pi * column / columns),
         math.sin(2.0 * math.pi * column / columns), row)
        for row in range(rows)
        for column in range(columns)
    ]
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
        self.assertEqual(bpy.ops.autoseamuv.validate_symmetry(), {"CANCELLED"})
        layer = obj.data.uv_layers.new(name="UVMap")
        for index, uv in enumerate(((0,0),(1,0),(1,1),(0,1))): layer.uv[index].vector = uv
        self.assertEqual(bpy.ops.autoseamuv.validate_symmetry(), {"FINISHED"})
        settings.symmetry_layout = "OVERLAP"
        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})
        settings.symmetry_layout = "SEPARATE_MIRRORED"
        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})

    def test_ring_unwrap_restores_partial_face_selection_and_select_mode(self):
        obj = ring_object()
        selected_faces = set(range(8))

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.object.mode_set(mode="OBJECT")
        for polygon in obj.data.polygons:
            polygon.select = polygon.index in selected_faces
        bpy.ops.object.mode_set(mode="EDIT")

        original_select_mode = tuple(bpy.context.tool_settings.mesh_select_mode)
        self.assertEqual(bpy.ops.autoseamuv.unwrap_ring_strip(), {"FINISHED"})

        edit_mesh = bmesh.from_edit_mesh(obj.data)
        edit_mesh.faces.ensure_lookup_table()
        restored_faces = {face.index for face in edit_mesh.faces if face.select}
        self.assertEqual(restored_faces, selected_faces)
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), original_select_mode)


suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
