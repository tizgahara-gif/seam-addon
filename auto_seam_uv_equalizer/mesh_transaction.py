"""Value-only snapshots and rollback for destructive Mesh operations.

The snapshot deliberately contains no UV-layer RNA members.  Blender can
invalidate those members during mode switches and UV collection mutations, so
rollback always reacquires a layer from its saved name.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UVLayerSnapshot:
    index: int
    name: str
    coordinates: tuple
    active: bool
    active_render: bool
    active_clone: bool
    pins: tuple
    vertex_selection: tuple
    edge_selection: tuple


@dataclass(frozen=True)
class MeshSnapshot:
    mesh: object
    seams: tuple
    layers: tuple
    active_name: str | None
    vertex_selection: tuple
    edge_selection: tuple
    face_selection: tuple


def _bool_values(layer, attribute, size):
    collection = getattr(layer, attribute, None)
    if collection is None:
        return (False,) * size
    return tuple(bool(item.value) for item in collection)


def snapshot_meshes(objects):
    """Snapshot each distinct Mesh ID before the caller's first write."""
    result = {}
    for obj in objects:
        mesh = obj.data
        key = mesh.as_pointer()
        if key in result:
            continue
        active = mesh.uv_layers.active
        layers = tuple(UVLayerSnapshot(
            index, layer.name,
            tuple(tuple(datum.vector) for datum in layer.uv),
            bool(layer.active), bool(layer.active_render), bool(layer.active_clone),
            _bool_values(layer, "pin", len(layer.uv)),
            _bool_values(layer, "vertex_selection", len(layer.uv)),
            _bool_values(layer, "edge_selection", len(layer.uv)),
        ) for index, layer in enumerate(mesh.uv_layers))
        result[key] = MeshSnapshot(
            mesh, tuple(edge.use_seam for edge in mesh.edges), layers,
            active.name if active is not None else None,
            tuple(vertex.select for vertex in mesh.vertices),
            tuple(edge.select for edge in mesh.edges),
            tuple(face.select for face in mesh.polygons),
        )
    return result


def _restore_boolean_layer(layer, attribute, values):
    collection = getattr(layer, attribute, None)
    if collection is None:
        if any(values):
            raise RuntimeError(f"UV {attribute} state is unavailable")
        return
    if len(collection) != len(values):
        raise RuntimeError(f"UV {attribute} length changed")
    for item, value in zip(collection, values):
        item.value = value


def restore_meshes(snapshot):
    """Restore a snapshot, attempting every Mesh and reporting all failures."""
    errors = []
    for state in snapshot.values():
        mesh = state.mesh
        try:
            if (len(mesh.edges) != len(state.seams) or
                    len(mesh.vertices) != len(state.vertex_selection) or
                    len(mesh.polygons) != len(state.face_selection)):
                raise RuntimeError(f"{mesh.name}: topology changed")

            original_names = tuple(item.name for item in state.layers)
            current_names = tuple(layer.name for layer in mesh.uv_layers)
            missing = [name for name in original_names if name not in current_names]
            if missing:
                raise RuntimeError(
                    f"{mesh.name}: original UV map(s) removed or renamed: {', '.join(missing)}")
            # Operations covered by this transaction may create maps, but never
            # remove or rename an existing one. Remove additions in reverse and
            # reacquire after each collection mutation.
            for name in reversed(tuple(name for name in current_names
                                       if name not in original_names)):
                layer = mesh.uv_layers.get(name)
                if layer is None:
                    raise RuntimeError(f"{mesh.name}: cannot reacquire new UV map {name}")
                mesh.uv_layers.remove(layer)
            if tuple(layer.name for layer in mesh.uv_layers) != original_names:
                raise RuntimeError(f"{mesh.name}: UV map order changed")

            for layer in mesh.uv_layers:
                layer.active_render = False
                layer.active_clone = False
            for item in state.layers:
                layer = mesh.uv_layers.get(item.name)
                if layer is None or len(layer.uv) != len(item.coordinates):
                    raise RuntimeError(f"{mesh.name}: UV map {item.name} changed")
                for datum, coordinate in zip(layer.uv, item.coordinates):
                    datum.vector = coordinate
                _restore_boolean_layer(layer, "pin", item.pins)
                _restore_boolean_layer(layer, "vertex_selection", item.vertex_selection)
                _restore_boolean_layer(layer, "edge_selection", item.edge_selection)
                layer.active_render = item.active_render
                layer.active_clone = item.active_clone
            if state.active_name is not None:
                active = mesh.uv_layers.get(state.active_name)
                if active is None:
                    raise RuntimeError(f"{mesh.name}: active UV map is unavailable")
                mesh.uv_layers.active = active

            for edge, value in zip(mesh.edges, state.seams):
                edge.use_seam = value
            for vertex, value in zip(mesh.vertices, state.vertex_selection):
                vertex.select = value
            for edge, value in zip(mesh.edges, state.edge_selection):
                edge.select = value
            for face, value in zip(mesh.polygons, state.face_selection):
                face.select = value
            mesh.update()
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        raise RuntimeError("; ".join(errors))


def rollback_error(operation, original, rollback):
    return RuntimeError(
        f"{operation} failed: {original}; rollback also failed: {rollback}")


def run_transaction(objects, operation, label="Mesh operation"):
    """Run an operation atomically across the supplied Mesh IDs."""
    before = snapshot_meshes(objects)
    try:
        return operation()
    except Exception as original:
        try:
            restore_meshes(before)
        except Exception as rollback:
            raise rollback_error(label, original, rollback) from original
        raise
