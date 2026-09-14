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
from auto_seam_uv_equalizer.symmetry import build_symmetry_plan


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
                     "unwrap_only", "grid_layout", "pack_islands", "auto_unwrap_pack",
                     "detect_ring_strip", "unwrap_ring_strip", "mirror_seams",
                     "validate_symmetry", "transfer_symmetric_uv"):
            self.assertTrue(hasattr(bpy.ops.autoseamuv, name), name)

    def test_independent_grid_and_pack_preserve_mesh_and_edit_selection(self):
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
        settings.grid_scale_mode = "PRESERVE_SCALE"
        settings.equal_region_layout = "HORIZONTAL_STRIP"
        self.assertEqual(bpy.ops.autoseamuv.grid_layout(), {"FINISHED"})
        self.assertEqual(topology, (len(obj.data.vertices), len(obj.data.edges), len(obj.data.polygons)))
        self.assertEqual(seams, tuple(edge.use_seam for edge in obj.data.edges))
        for start, expected in zip((0, 4), island_sizes):
            coords = [tuple(layer.uv[index].vector) for index in range(start, start + 4)]
            bounds = uv_bounds(coords)
            self.assertAlmostEqual(bounds[1] - bounds[0], expected[0])
            self.assertAlmostEqual(bounds[3] - bounds[2], expected[1])

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

    def test_goz_symmetric_clothing_workflow_regression(self):
        """Ticket 17: exercise the complete GoZ-equivalent workflow in order."""
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

        settings = bpy.context.scene.autoseamuv_settings
        settings.uv_map_name = target.name
        settings.ring_seam_mode = "AUTO"
        settings.symmetry_axis = "X"
        settings.symmetry_direction = "NEGATIVE_TO_POSITIVE"
        settings.symmetry_scope = "SELECTED"
        settings.symmetry_layout = "OVERLAP"

        def assert_invariants(stage):
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
        run_stage("Ring / Strip Unwrap", bpy.ops.autoseamuv.unwrap_ring_strip)
        run_stage("Validate Symmetry", bpy.ops.autoseamuv.validate_symmetry)
        run_stage("Transfer Symmetric UV", bpy.ops.autoseamuv.transfer_symmetric_uv)

        plan = build_symmetry_plan(
            [tuple(vertex.co) for vertex in mesh.vertices],
            [tuple(edge.vertices) for edge in mesh.edges],
            [tuple(face.vertices) for face in mesh.polygons],
            [face for face in selected_faces
             if all(mesh.vertices[vertex].co.x <= settings.symmetry_tolerance
                    for vertex in mesh.polygons[face].vertices)
             and any(mesh.vertices[vertex].co.x < -settings.symmetry_tolerance
                     for vertex in mesh.polygons[face].vertices)],
            axis=0,
            source_sign=-1,
            tolerance=settings.symmetry_tolerance,
        )
        for source_loop, destination_loop in plan.loop_pairs:
            self.assertAlmostEqual(target.uv[source_loop].vector.x,
                                   target.uv[destination_loop].vector.x, places=6)
            self.assertAlmostEqual(target.uv[source_loop].vector.y,
                                   target.uv[destination_loop].vector.y, places=6)

        run_stage("Auto Unwrap / Pack", bpy.ops.autoseamuv.auto_unwrap_pack)
        self.assertTrue(all(
            math.isfinite(component)
            for datum in target.uv
            for component in datum.vector
        ), "Auto Unwrap / Pack: target UV contains a non-finite coordinate")


suite = unittest.defaultTestLoader.loadTestsFromTestCase(IntegrationTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful():
    raise SystemExit(1)
