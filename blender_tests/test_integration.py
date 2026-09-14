"""Blender 5.1 runtime/registration and core-workflow smoke tests."""
import math
import pathlib
import sys
import unittest

import bmesh
import bpy
import bmesh

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
            self.assertEqual(tuple(layer.uv[destination_loop].vector),
                             source_uvs[source_loop])
        settings.symmetry_layout = "SEPARATE_MIRRORED"
        settings.symmetry_island_gap = 0.25
        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})

    def test_symmetric_uv_transfer_restores_edit_mode_face_selection(self):
        obj = mesh_object("SymmetricSelection", [(-1,0,0),(-1,1,0),(-1,1,1),(-1,0,1),
                                                  (1,0,0),(1,0,1),(1,1,1),(1,1,0)],
                          [(0,1,2,3),(4,5,6,7)])
        layer = obj.data.uv_layers.new(name="UVMap")
        for index, uv in enumerate(((0,0),(1,0),(1,1),(0,1))):
            layer.uv[index].vector = uv

        settings = bpy.context.scene.autoseamuv_settings
        settings.symmetry_axis = "X"
        settings.symmetry_direction = "NEGATIVE_TO_POSITIVE"
        settings.symmetry_scope = "SELECTED"
        settings.symmetry_layout = "OVERLAP"

        bpy.ops.object.mode_set(mode="EDIT")
        bpy.context.tool_settings.mesh_select_mode = (False, False, True)
        bpy.ops.mesh.select_all(action="DESELECT")
        edit_mesh = bmesh.from_edit_mesh(obj.data)
        edit_mesh.faces.ensure_lookup_table()
        edit_mesh.faces[0].select_set(True)
        bmesh.update_edit_mesh(obj.data)
        original_selection = {face.index for face in edit_mesh.faces if face.select}
        self.assertEqual(original_selection, {0})

        self.assertEqual(bpy.ops.autoseamuv.transfer_symmetric_uv(), {"FINISHED"})

        self.assertEqual(obj.mode, "EDIT")
        edit_mesh = bmesh.from_edit_mesh(obj.data)
        edit_mesh.faces.ensure_lookup_table()
        restored_selection = {face.index for face in edit_mesh.faces if face.select}
        self.assertEqual(restored_selection, original_selection)


suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
