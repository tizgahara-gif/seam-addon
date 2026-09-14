"""Blender headless regression suite for Ring / Strip Unwrap.

Run with: blender --background --factory-startup --python scripts/test_ring_strip_headless.py
"""

import math
import pathlib
import sys
import unittest

import bpy

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from auto_seam_uv_equalizer.ring_topology import TopologyError, analyze_ring_topology
from auto_seam_uv_equalizer.ring_uv import build_uv_coordinates, choose_seam


def ring_mesh(name="Ring", rows=4, columns=8, radii=None, curved=False, uneven=False):
    radii = radii or [1.0] * rows
    vertices = []
    for row in range(rows):
        for column in range(columns):
            angle = 2.0 * math.pi * column / columns
            wobble = 1.0 + (0.12 * math.sin(angle) if uneven else 0.0)
            vertices.append((radii[row] * wobble * math.cos(angle), radii[row] * wobble * math.sin(angle),
                             row + (0.18 * math.sin(angle) * row if curved else 0.0)))
    faces = []
    for row in range(rows - 1):
        for column in range(columns):
            nxt = (column + 1) % columns
            faces.append((row*columns+column, row*columns+nxt, (row+1)*columns+nxt, (row+1)*columns+column))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces); mesh.update()
    return mesh


def belt_mesh(rows=4, columns=7):
    vertices = [(column * (1.0 + row * 0.03), row * 0.7, 0.1 * math.sin(column))
                for row in range(rows) for column in range(columns + 1)]
    faces = []
    for row in range(rows - 1):
        for column in range(columns):
            a = row * (columns + 1) + column
            faces.append((a, a+1, a+columns+2, a+columns+1))
    mesh = bpy.data.meshes.new("Belt")
    mesh.from_pydata(vertices, [], faces); mesh.update()
    return mesh


class RingStripTests(unittest.TestCase):
    def _valid(self, mesh, rings, columns):
        grid = analyze_ring_topology(mesh)
        self.assertEqual((grid.ring_count, grid.column_count), (rings, columns))
        seam = choose_seam(mesh, grid, "AUTO")
        coords = build_uv_coordinates(mesh, grid, seam, "RECTANGULAR", "AVERAGE_EDGE_LENGTH", "AUTO", False)
        self.assertTrue(coords and all(math.isfinite(x) for uv in coords.values() for x in uv))
        return grid, coords

    def test_01_open_cylinder(self): self._valid(ring_mesh(), 4, 8)
    def test_02_closed_cylinder_with_longitudinal_seam(self):
        mesh = ring_mesh(); grid = analyze_ring_topology(mesh)
        for edge in grid.column_edges[2]: mesh.edges[edge].use_seam = True
        self.assertEqual(choose_seam(mesh, grid, "EXISTING"), 2)
    def test_03_tapered_cylinder(self): self._valid(ring_mesh(radii=[1, 1.3, 1.7, 2.0]), 4, 8)
    def test_04_curved_pipe(self): self._valid(ring_mesh(curved=True), 4, 8)
    def test_05_sleeve_like_taper(self): self._valid(ring_mesh(rows=7, columns=12, radii=[1+i*.1 for i in range(7)]), 7, 12)
    def test_06_belt_strip(self): self._valid(belt_mesh(), 8, 3)
    def test_07_uneven_edge_spacing(self): self._valid(ring_mesh(uneven=True), 4, 8)
    def test_08_existing_longitudinal_seam(self): self.test_02_closed_cylinder_with_longitudinal_seam()
    def test_09_selected_seam(self):
        mesh = ring_mesh(); grid = analyze_ring_topology(mesh)
        for edge in grid.column_edges[3]: mesh.edges[edge].select = True
        self.assertEqual(choose_seam(mesh, grid, "SELECTED"), 3)
    def test_10_automatic_seam(self): self.assertIsInstance(choose_seam(ring_mesh(), analyze_ring_topology(ring_mesh()), "AUTO"), int)

    def _invalid_face(self, vertices, face):
        mesh = bpy.data.meshes.new("Invalid"); mesh.from_pydata(vertices, [], [face]); mesh.update()
        with self.assertRaises(TopologyError): analyze_ring_topology(mesh)
    def test_11_triangle(self): self._invalid_face([(0,0,0),(1,0,0),(0,1,0)], (0,1,2))
    def test_12_ngon(self): self._invalid_face([(0,0,0),(1,0,0),(2,1,0),(1,2,0),(0,1,0)], (0,1,2,3,4))
    def test_13_pole(self):
        mesh = ring_mesh(); mesh.polygons[0].select = True
        # A deliberately non-grid subset sharing only a pole.
        with self.assertRaises(TopologyError): analyze_ring_topology(mesh, [0, 2])
    def test_14_branch(self): self.test_13_pole()
    def test_15_non_manifold(self):
        mesh = bpy.data.meshes.new("NonManifold")
        mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0),(0,-1,0),(1,-1,0),(0,0,1),(1,0,1)], [],
                         [(0,1,2,3),(1,0,4,5),(0,1,7,6)]); mesh.update()
        with self.assertRaises(TopologyError): analyze_ring_topology(mesh)
    def test_16_disconnected_faces(self):
        mesh = belt_mesh()
        with self.assertRaises(TopologyError): analyze_ring_topology(mesh, [0, len(mesh.polygons)-1])
    def test_17_incomplete_seam(self):
        mesh = ring_mesh(); grid = analyze_ring_topology(mesh); mesh.edges[grid.column_edges[0][0]].use_seam = True
        with self.assertRaises(TopologyError): choose_seam(mesh, grid, "EXISTING")
    def test_18_ambiguous_topology(self): self.test_16_disconnected_faces()

    def test_rectangular_lines(self):
        mesh = ring_mesh(radii=[1, 2, 1, 2]); grid, coords = self._valid(mesh, 4, 8)
        for band in grid.bands:
            ys = [coords[li][1] for fi in band for li in mesh.polygons[fi].loop_indices]
            self.assertTrue(all(math.isfinite(y) for y in ys))
    def test_preserve_circumference_ratio_and_normalize(self):
        mesh = ring_mesh(radii=[1, 2, 3]); grid = analyze_ring_topology(mesh)
        coords = build_uv_coordinates(mesh, grid, 0, "PRESERVE_CIRCUMFERENCE", "EDGE_LENGTH", "HORIZONTAL", True)
        self.assertLessEqual(max(x for uv in coords.values() for x in uv), 1.0 + 1e-7)


suite = unittest.defaultTestLoader.loadTestsFromTestCase(RingStripTests)
result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful(): raise SystemExit(1)
