"""UV layout and loop-level assignment for :mod:`ring_topology`."""

from __future__ import annotations

from math import isfinite

from .ring_topology import TopologyError


def _length(mesh, a, b):
    return (mesh.vertices[a].co - mesh.vertices[b].co).length


def choose_seam(mesh, grid, mode):
    """Return a column index, honoring complete existing/selected paths."""
    candidates = list(range(len(grid.column_edges)))
    complete_existing = [c for c in candidates if all(mesh.edges[e].use_seam for e in grid.column_edges[c])]
    complete_selected = [c for c in candidates if all(mesh.edges[e].select for e in grid.column_edges[c])]
    if mode == "EXISTING":
        if len(complete_existing) != 1: raise TopologyError("existing seam is incomplete or ambiguous")
        return complete_existing[0]
    if mode == "SELECTED":
        if len(complete_selected) != 1: raise TopologyError("selected seam is incomplete or ambiguous")
        return complete_selected[0]
    # Existing markings dominate; then prefer continuous, low-curvature and
    # material-boundary paths. Protected paths are excluded.
    attrs = getattr(mesh, "attributes", {})
    protect = attrs.get("protect_seam") if hasattr(attrs, "get") else None
    force = attrs.get("force_seam") if hasattr(attrs, "get") else None
    edge_faces = {edge.index: [] for edge in mesh.edges}
    by_vertices = {tuple(sorted(edge.vertices)): edge.index for edge in mesh.edges}
    for face in mesh.polygons:
        verts = tuple(face.vertices)
        for i in range(len(verts)):
            edge_faces[by_vertices[tuple(sorted((verts[i], verts[(i + 1) % len(verts)]))) ]].append(face)
    scored = []
    for c in candidates:
        edges = grid.column_edges[c]
        if protect and any(protect.data[e].value for e in edges): continue
        score = sum(100.0 for e in edges if mesh.edges[e].use_seam)
        if force: score += sum(200.0 for e in edges if force.data[e].value)
        for edge_index in edges:
            faces = edge_faces[edge_index]
            if len(faces) == 2:
                if faces[0].material_index != faces[1].material_index: score += 12.0
                # Lower dihedral curvature is less visually objectionable.
                score -= faces[0].normal.angle(faces[1].normal)
        score -= sum(_length(mesh, *mesh.edges[e].vertices) for e in edges) * 1.0e-6
        scored.append((score, -c, c))
    if not scored: raise TopologyError("all seam candidates are protected")
    return max(scored)[2]


def build_uv_coordinates(mesh, grid, seam_column, layout, spacing, orientation, normalize):
    """Compute all loop coordinates without modifying the mesh."""
    rings = [list(r) for r in grid.rings]
    if grid.closed:
        rings = [ring[seam_column:] + ring[:seam_column] for ring in rings]
    columns = len(rings[0]) if grid.closed else len(rings[0]) - 1
    segment_lengths = [[_length(mesh, ring[c], ring[(c + 1) % len(ring)]) for c in range(columns)] for ring in rings]
    circumferences = [sum(row) for row in segment_lengths]
    average_segments = [sum(row[c] for row in segment_lengths) / len(rings) for c in range(columns)]
    if spacing == "EVEN": proportions = [1.0 / columns] * columns
    else:
        total_avg = sum(average_segments)
        proportions = [value / total_avg for value in average_segments]
    target_width = sum(circumferences) / len(circumferences)
    us = []
    for row, lengths in enumerate(segment_lengths):
        # A rectangular grid must share every U column.  EDGE_LENGTH therefore
        # uses the corresponding-edge average in this layout.
        if layout == "RECTANGULAR": parts = proportions
        elif spacing == "EDGE_LENGTH": parts = [v / circumferences[row] for v in lengths]
        else: parts = proportions
        width = target_width if layout == "RECTANGULAR" else circumferences[row]
        values = [0.0]
        for part in parts: values.append(values[-1] + part * width)
        us.append(values)
    vertical = [[_length(mesh, rings[r][c], rings[r + 1][c]) for c in range(len(rings[0]))] for r in range(len(rings) - 1)]
    vs = [0.0]
    for values in vertical:
        step = 1.0 if spacing == "EVEN" else (sum(values) / len(values) if spacing == "AVERAGE_EDGE_LENGTH" or layout == "RECTANGULAR" else sum(values) / len(values))
        vs.append(vs[-1] + step)
    coords = {}
    for r, band in enumerate(grid.bands):
        for c, fi in enumerate(band):
            logical_c = c
            # Bands retain original order; rotate their lookup for a closed seam.
            if grid.closed: fi = band[(c + seam_column) % len(band)]
            left, right = rings[r][c], rings[r][(c + 1) % len(rings[r])]
            next_left, next_right = rings[r + 1][c], rings[r + 1][(c + 1) % len(rings[r + 1])]
            mapping = {left:(us[r][logical_c],vs[r]), right:(us[r][logical_c+1],vs[r]),
                       next_left:(us[r+1][logical_c],vs[r+1]), next_right:(us[r+1][logical_c+1],vs[r+1])}
            poly = mesh.polygons[fi]
            for li, vertex in zip(poly.loop_indices, poly.vertices): coords[li] = mapping[vertex]
    if orientation in {"HORIZONTAL", "AUTO"}:
        pass
    else:
        coords = {li:(v, u) for li,(u,v) in coords.items()}
    if normalize:
        xs, ys = zip(*coords.values()); scale = max(max(xs)-min(xs), max(ys)-min(ys))
        if scale <= 0: raise TopologyError("UV layout has zero area")
        coords = {li:((u-min(xs))/scale, (v-min(ys))/scale) for li,(u,v) in coords.items()}
    if any(not isfinite(value) for uv in coords.values() for value in uv): raise TopologyError("UV layout is not finite")
    return coords


def assign_uv_loops(mesh, uv_layer, coordinates):
    """Commit a previously validated layout to MeshLoopUV records."""
    for loop_index, uv in coordinates.items():
        uv_layer.data[loop_index].uv = uv
    mesh.update()
