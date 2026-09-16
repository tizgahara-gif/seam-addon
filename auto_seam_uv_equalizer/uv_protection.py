"""Persistent, explicit protection for seam and UV editing operations.

Protection deliberately lives on Mesh face attributes rather than UV pins.  The
helpers in this module are the single policy boundary used by every mutating
operator; missing attributes mean an entirely unprotected legacy mesh.
"""

from __future__ import annotations

from dataclasses import dataclass

from .island_tools import find_uv_islands
from .mesh_utils import build_mesh_topology


FINISHED_ATTRIBUTE = "autoseam_finished_group"
LAYOUT_LOCK_ATTRIBUTE = "autoseam_layout_lock"
CONFLICT_MESSAGE = "Protection state is inconsistent. Re-tag or clear protection."


class ProtectionError(RuntimeError):
    """A controlled protection-policy or consistency failure."""


@dataclass(frozen=True)
class ProtectionState:
    finished_group: int = 0
    layout_locked: bool = False

    @property
    def finished(self):
        return self.finished_group > 0

    @property
    def effectively_layout_locked(self):
        return self.finished or self.layout_locked


def _attribute(mesh, name):
    attribute = mesh.attributes.get(name)
    if attribute is None or attribute.domain != "FACE" or attribute.data_type != "INT":
        return None
    return attribute


def ensure_attributes(mesh):
    """Create and return the two persistent face-domain integer attributes."""
    finished = _attribute(mesh, FINISHED_ATTRIBUTE)
    locked = _attribute(mesh, LAYOUT_LOCK_ATTRIBUTE)
    if finished is None:
        old = mesh.attributes.get(FINISHED_ATTRIBUTE)
        if old is not None:
            raise ProtectionError(f"{FINISHED_ATTRIBUTE} must be a face-domain INT attribute")
        finished = mesh.attributes.new(FINISHED_ATTRIBUTE, "INT", "FACE")
    if locked is None:
        old = mesh.attributes.get(LAYOUT_LOCK_ATTRIBUTE)
        if old is not None:
            raise ProtectionError(f"{LAYOUT_LOCK_ATTRIBUTE} must be a face-domain INT attribute")
        locked = mesh.attributes.new(LAYOUT_LOCK_ATTRIBUTE, "INT", "FACE")
    return finished, locked


def get_finished_group(face, mesh=None):
    """Read a group from a Mesh polygon or a BMesh face."""
    if mesh is not None:
        attribute = _attribute(mesh, FINISHED_ATTRIBUTE)
        return int(attribute.data[face.index].value) if attribute else 0
    layer = face.id_data.faces.layers.int.get(FINISHED_ATTRIBUTE)
    return int(face[layer]) if layer else 0


def is_face_finished(face, mesh=None):
    return get_finished_group(face, mesh) > 0


def island_state(mesh, face_indices):
    finished = _attribute(mesh, FINISHED_ATTRIBUTE)
    locked = _attribute(mesh, LAYOUT_LOCK_ATTRIBUTE)
    groups = {int(finished.data[index].value) if finished else 0 for index in face_indices}
    locks = {int(locked.data[index].value) != 0 if locked else False for index in face_indices}
    if len(groups) > 1 or len(locks) > 1:
        raise ProtectionError(CONFLICT_MESSAGE)
    return ProtectionState(next(iter(groups), 0), next(iter(locks), False))


def is_island_finished(island, mesh=None):
    mesh = mesh or island.mesh
    return island_state(mesh, island.face_indices).finished


def is_island_layout_locked(island, mesh=None):
    mesh = mesh or island.mesh
    return island_state(mesh, island.face_indices).layout_locked


def is_island_effectively_layout_locked(island, mesh=None):
    mesh = mesh or island.mesh
    return island_state(mesh, island.face_indices).effectively_layout_locked


def current_islands(obj):
    """Return current active-map UV islands as deterministic face tuples."""
    if obj.data.uv_layers.active is None:
        raise ProtectionError("No active UV map.")
    _, _, loop_to_face, _ = build_mesh_topology(obj.data)
    return [tuple(sorted({loop_to_face[loop] for loop in loops}))
            for loops in find_uv_islands(obj)]


def validate_protection_consistency(obj, islands=None):
    islands = current_islands(obj) if islands is None else islands
    return [island_state(obj.data, faces) for faces in islands]


def collect_finished_islands(obj):
    islands = current_islands(obj)
    states = validate_protection_consistency(obj, islands)
    return [faces for faces, state in zip(islands, states) if state.finished]


def collect_layout_locked_islands(obj, effective=False):
    islands = current_islands(obj)
    states = validate_protection_consistency(obj, islands)
    return [faces for faces, state in zip(islands, states)
            if (state.effectively_layout_locked if effective else state.layout_locked)]


def finished_face_indices(mesh):
    attribute = _attribute(mesh, FINISHED_ATTRIBUTE)
    return ({index for index, value in enumerate(attribute.data) if int(value.value) > 0}
            if attribute else set())


def edge_touches_finished_region(mesh, edge, edge_faces=None):
    if edge_faces is None:
        from .mesh_utils import build_edge_to_faces
        edge_faces = build_edge_to_faces(mesh)
    return any(index in finished_face_indices(mesh) for index in edge_faces.get(edge.index, ()))


def protected_edge_indices(mesh, edge_faces=None):
    faces = finished_face_indices(mesh)
    if not faces:
        return set()
    if edge_faces is None:
        from .mesh_utils import build_edge_to_faces
        edge_faces = build_edge_to_faces(mesh)
    return {edge.index for edge in mesh.edges
            if any(face in faces for face in edge_faces.get(edge.index, ())) }


def finished_loop_indices(mesh):
    faces = finished_face_indices(mesh)
    return {loop for index in faces for loop in mesh.polygons[index].loop_indices}


def assert_plan_does_not_modify_finished(mesh, loop_indices=(), edge_indices=()):
    """Final write barrier for a pending UV/seam transaction."""
    bad_loops = set(loop_indices) & finished_loop_indices(mesh)
    bad_edges = set(edge_indices) & protected_edge_indices(mesh)
    if bad_loops or bad_edges:
        raise ProtectionError("internal protection violation")


def snapshot_finished(mesh):
    layer = mesh.uv_layers.active
    loops = finished_loop_indices(mesh)
    return {
        "uv": {index: tuple(layer.uv[index].vector) for index in loops} if layer else {},
        "seams": {index: bool(mesh.edges[index].use_seam)
                  for index in protected_edge_indices(mesh)},
    }


def selected_islands(obj, selected_faces):
    islands = current_islands(obj)
    return [faces for faces in islands if set(faces) & set(selected_faces)]


def assign_selected_islands(obj, selected_faces, kind, value):
    """Assign an entire current island for each selected face seed."""
    islands = selected_islands(obj, selected_faces)
    if not islands:
        raise ProtectionError("No selected UV islands found.")
    finished, locked = ensure_attributes(obj.data)
    if kind == "finished":
        next_group = max((int(item.value) for item in finished.data), default=0) + 1
        for faces in islands:
            group = next_group if value else 0
            next_group += bool(value)
            for index in faces:
                finished.data[index].value = group
    elif kind == "layout":
        for faces in islands:
            for index in faces:
                locked.data[index].value = int(bool(value))
    else:
        raise ValueError(kind)
    obj.data.update()
    return len(islands)
