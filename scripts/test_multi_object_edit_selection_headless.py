"""Test multi-object Edit Mode selection snapshots in headless Blender.

Run with: blender --background --factory-startup --python scripts/test_multi_object_edit_selection_headless.py
"""

import pathlib
import sys

import bmesh
import bpy


sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from auto_seam_uv_equalizer.operators import (
    _EDIT_SELECTION_SNAPSHOTS,
    _restore_context,
    _snapshot_context,
)


def make_quad(name, x_offset):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(
        [(x_offset, 0, 0), (x_offset + 1, 0, 0),
         (x_offset + 1, 1, 0), (x_offset, 1, 0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def selection(mesh):
    bm = bmesh.from_edit_mesh(mesh)
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    return (
        {item.index for item in bm.verts if item.select},
        {item.index for item in bm.edges if item.select},
        {item.index for item in bm.faces if item.select},
    )


first = make_quad("First", 0)
second = make_quad("Second", 2)
linked = bpy.data.objects.new("FirstLinked", first.data)
bpy.context.collection.objects.link(linked)

for obj in (first, second, linked):
    obj.select_set(True)
bpy.context.view_layer.objects.active = first
bpy.ops.object.mode_set(mode="EDIT")

first_bm = bmesh.from_edit_mesh(first.data)
second_bm = bmesh.from_edit_mesh(second.data)
for bm in (first_bm, second_bm):
    bm.verts.ensure_lookup_table(); bm.edges.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    for item in (*bm.verts, *bm.edges, *bm.faces):
        item.select = False

first_bm.verts[0].select = True
first_bm.edges[1].select = True
second_bm.verts[2].select = True
second_bm.edges[3].select = True
second_bm.faces[0].select = True
bpy.context.tool_settings.mesh_select_mode = (True, True, True)

expected = {first.data.as_pointer(): selection(first.data), second.data.as_pointer(): selection(second.data)}
active, selected, mode = _snapshot_context(bpy.context)
assert len(_EDIT_SELECTION_SNAPSHOTS) == 2  # The linked objects share one snapshot.

# Simulate an operator that destroys all three component-selection categories.
for mesh in (first.data, second.data):
    bm = bmesh.from_edit_mesh(mesh)
    for item in (*bm.verts, *bm.edges, *bm.faces):
        item.select = not item.select
bpy.context.tool_settings.mesh_select_mode = (False, False, True)

_restore_context(bpy.context, active, selected, mode)

assert bpy.context.mode == "EDIT_MESH"
assert bpy.context.view_layer.objects.active == first
assert set(bpy.context.selected_objects) == {first, second, linked}
assert tuple(bpy.context.tool_settings.mesh_select_mode) == (True, True, True)
assert selection(first.data) == expected[first.data.as_pointer()]
assert selection(second.data) == expected[second.data.as_pointer()]
# Linked users must observe the single restored selection on their shared Mesh.
assert linked.data is first.data

print("Multi-object Edit Mode selection snapshot test passed")
