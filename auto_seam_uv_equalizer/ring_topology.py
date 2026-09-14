"""Linear-time topology recovery for regular quad rings and strips.

This module deliberately knows nothing about UV layers.  It turns mesh topology
into ordered vertex rings and face bands; callers may safely validate a result
before creating or touching UV data.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict, deque


class TopologyError(ValueError):
    """The selected component cannot be represented by one rectangular grid."""


@dataclass(frozen=True)
class RingGrid:
    face_indices: tuple[int, ...]
    rings: tuple[tuple[int, ...], ...]
    bands: tuple[tuple[int, ...], ...]
    closed: bool
    boundary_count: int
    column_edges: tuple[tuple[int, ...], ...]

    @property
    def ring_count(self):
        return len(self.rings)

    @property
    def column_count(self):
        return len(self.rings[0]) - (0 if self.closed else 1)


def _edge_key(a, b):
    return (a, b) if a < b else (b, a)


def _ordered_boundary(vertices, adjacency, closed):
    starts = [v for v in vertices if len(adjacency[v]) == 1]
    if closed:
        if any(len(adjacency[v]) != 2 for v in vertices):
            raise TopologyError("branched boundary loop")
        start = min(vertices)
    else:
        if len(starts) != 2 or any(len(adjacency[v]) not in {1, 2} for v in vertices):
            raise TopologyError("branched boundary path")
        start = min(starts)
    result, previous, current = [], None, start
    while True:
        result.append(current)
        candidates = [v for v in adjacency[current] if v != previous]
        if not candidates:
            break
        nxt = candidates[0]
        if nxt == start:
            break
        if nxt in result:
            raise TopologyError("boundary self-intersection")
        previous, current = current, nxt
    if len(result) != len(vertices):
        raise TopologyError("boundary traversal did not visit every vertex")
    return result


def analyze_ring_topology(mesh, face_indices=None):
    """Validate *face_indices* and recover an ordered quad grid.

    Faces, edges and vertices are indexed using Blender's Mesh API, but the
    implementation only relies on its public sequence attributes, which keeps
    the algorithm testable and independent from edit/object mode.
    """
    selected = tuple(sorted(face_indices if face_indices is not None else range(len(mesh.polygons))))
    if not selected:
        raise TopologyError("no faces selected")
    selected_set = set(selected)
    edge_faces, face_edges, vertex_faces = defaultdict(list), {}, defaultdict(list)
    edge_index = {_edge_key(*e.vertices): e.index for e in mesh.edges}
    global_edge_faces = defaultdict(int)
    for face in mesh.polygons:
        verts = tuple(face.vertices)
        for i in range(len(verts)):
            global_edge_faces[_edge_key(verts[i], verts[(i + 1) % len(verts)])] += 1
    for fi in selected:
        face = mesh.polygons[fi]
        verts = tuple(face.vertices)
        if len(verts) != 4:
            raise TopologyError("selected component contains a triangle or N-gon")
        edges = tuple(_edge_key(verts[i], verts[(i + 1) % 4]) for i in range(4))
        face_edges[fi] = edges
        for edge in edges:
            edge_faces[edge].append(fi)
        for vertex in verts:
            vertex_faces[vertex].append(fi)
    if any(global_edge_faces[edge] > 2 for edge in edge_faces):
        raise TopologyError("non-manifold edge")

    neighbors = {fi: set() for fi in selected}
    for faces in edge_faces.values():
        if len(faces) == 2:
            neighbors[faces[0]].add(faces[1]); neighbors[faces[1]].add(faces[0])
    reached, queue = set(), deque([selected[0]])
    while queue:
        fi = queue.popleft()
        if fi in reached: continue
        reached.add(fi); queue.extend(neighbors[fi] - reached)
    if reached != selected_set:
        raise TopologyError("disconnected faces")

    boundary = [edge for edge, faces in edge_faces.items() if len(faces) == 1]
    if not boundary:
        raise TopologyError("closed surface has no boundary rings")
    bad_vertices = [v for v, faces in vertex_faces.items() if len(faces) not in {1, 2, 4}]
    if bad_vertices:
        raise TopologyError("pole or branch topology")
    boundary_adj = defaultdict(list)
    for a, b in boundary:
        boundary_adj[a].append(b); boundary_adj[b].append(a)
    components, unseen = [], set(boundary_adj)
    while unseen:
        todo, component = [next(iter(unseen))], set()
        while todo:
            v = todo.pop()
            if v in component: continue
            component.add(v); unseen.discard(v); todo.extend(boundary_adj[v])
        components.append(component)

    if len(components) == 2:
        initial = _ordered_boundary(components[0], boundary_adj, True)
        closed = True
    elif len(components) == 1:
        corners = [v for v in components[0] if len(vertex_faces[v]) == 1]
        if len(corners) != 4:
            raise TopologyError("strip boundary must have exactly four corners")
        cycle = _ordered_boundary(components[0], boundary_adj, True)
        positions = sorted(cycle.index(v) for v in corners)
        paths = []
        for i, pos in enumerate(positions):
            end = positions[(i + 1) % 4]
            path = cycle[pos:end + 1] if end > pos else cycle[pos:] + cycle[:end + 1]
            paths.append(path)
        initial = min(paths, key=lambda path: (len(path), tuple(path)))
        closed = False
    else:
        raise TopologyError("topology must have one strip boundary or two ring boundaries")

    rings, bands, used_faces = [tuple(initial)], [], set()
    while True:
        current = rings[-1]
        intervals = len(current) if closed else len(current) - 1
        next_vertices, band = [], []
        for column in range(intervals):
            a, b = current[column], current[(column + 1) % len(current)]
            candidates = [fi for fi in edge_faces[_edge_key(a, b)] if fi not in used_faces]
            if not candidates:
                if column == 0: break
                raise TopologyError("incomplete or inconsistent ring traversal")
            if len(candidates) != 1:
                raise TopologyError("opposite edge traversal is ambiguous")
            fi = candidates[0]
            verts = tuple(mesh.polygons[fi].vertices)
            ia, ib = verts.index(a), verts.index(b)
            if (ia + 1) % 4 == ib:
                na, nb = verts[(ia - 1) % 4], verts[(ib + 1) % 4]
            elif (ib + 1) % 4 == ia:
                na, nb = verts[(ia + 1) % 4], verts[(ib - 1) % 4]
            else:
                raise TopologyError("ring edge is not a face edge")
            if column == 0: next_vertices.append(na)
            elif next_vertices[-1] != na: raise TopologyError("ring columns do not join uniquely")
            if not closed or column < intervals - 1: next_vertices.append(nb)
            elif next_vertices[0] != nb: raise TopologyError("ring does not close")
            band.append(fi)
        if not band: break
        if len(band) != intervals or len(set(next_vertices)) != len(next_vertices):
            raise TopologyError("ring traversal revisited a vertex")
        used_faces.update(band); bands.append(tuple(band)); rings.append(tuple(next_vertices))
    if used_faces != selected_set:
        raise TopologyError("branch, pole, or ambiguous topology left unvisited faces")
    if any(len(ring) != len(rings[0]) for ring in rings):
        raise TopologyError("logical grid row/column counts differ")

    paths = []
    for column in range(len(rings[0])):
        path = []
        for row in range(len(rings) - 1):
            key = _edge_key(rings[row][column], rings[row + 1][column])
            if key not in edge_index: raise TopologyError("missing longitudinal edge")
            path.append(edge_index[key])
        paths.append(tuple(path))
    return RingGrid(selected, tuple(rings), tuple(bands), closed, len(components), tuple(paths))
