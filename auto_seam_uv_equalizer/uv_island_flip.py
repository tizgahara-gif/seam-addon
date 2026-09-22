"""Transactional horizontal transforms for selected UV islands."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .island_tools import find_uv_face_islands


@dataclass(frozen=True)
class UVFlipIsland:
    """An immutable snapshot of one complete UV island."""

    loop_uvs: tuple[tuple[tuple[int, int], float, float], ...]


def collect_selected_uv_islands(obj, bm, uv_layer) -> list[UVFlipIsland]:
    """Snapshot complete islands containing at least one selected mesh face.

    Connectivity comes directly from the live Edit BMesh through the shared
    mode-aware face-island helper. Selection is only read; it is never expanded
    or written.
    """
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    selected_faces = {face.index for face in bm.faces if face.select}
    if not selected_faces:
        return []

    islands = []
    for face_indices in find_uv_face_islands(obj):
        if not selected_faces.intersection(face_indices):
            continue
        loops = sorted(((face_index, corner_index, loop)
                        for face_index in face_indices
                        for corner_index, loop in enumerate(bm.faces[face_index].loops)),
                       key=lambda item: (item[0], item[1]))
        islands.append(UVFlipIsland(tuple(
            ((face_index, corner_index), float(loop[uv_layer].uv.x),
             float(loop[uv_layer].uv.y))
            for face_index, corner_index, loop in loops)))
    return islands


def plan_horizontal_uv_flip(islands: list[UVFlipIsland]) -> dict[tuple[int, int], tuple[float, float]]:
    """Validate snapshots and plan a per-island bounding-box-center U flip."""
    if not islands:
        raise ValueError("No selected UV islands found.")

    planned_uvs: dict[tuple[int, int], tuple[float, float]] = {}
    for island in islands:
        if not island.loop_uvs:
            raise ValueError("UV island has no loops.")
        if any(not (math.isfinite(u) and math.isfinite(v))
               for _loop_id, u, v in island.loop_uvs):
            raise ValueError("UV island has non-finite coordinates.")
        minimum_u = min(u for _loop_index, u, _v in island.loop_uvs)
        maximum_u = max(u for _loop_index, u, _v in island.loop_uvs)
        pivot_u = (minimum_u + maximum_u) * 0.5
        if not math.isfinite(pivot_u):
            raise ValueError("UV island has an invalid U bounding box.")
        for loop_index, old_u, old_v in island.loop_uvs:
            if loop_index in planned_uvs:
                raise ValueError("A UV loop belongs to more than one island.")
            planned_uvs[loop_index] = (2.0 * pivot_u - old_u, old_v)
    return planned_uvs


def apply_uv_plan(bm, uv_layer, planned_uvs: dict[tuple[int, int], tuple[float, float]]) -> None:
    """Commit a fully validated plan without touching any selection or flags."""
    bm.faces.ensure_lookup_table()
    for (face_index, corner_index), (u, v) in planned_uvs.items():
        bm.faces[face_index].loops[corner_index][uv_layer].uv = (u, v)


def mesh_loop_indices(mesh, loop_ids):
    """Resolve stable face/corner IDs to Mesh loop IDs after Edit sync."""
    result = {}
    for loop_id in loop_ids:
        face_index, corner_index = loop_id
        if face_index < 0 or face_index >= len(mesh.polygons):
            raise ValueError("UV plan contains an invalid face index.")
        loops = mesh.polygons[face_index].loop_indices
        if corner_index < 0 or corner_index >= len(loops):
            raise ValueError("UV plan contains an invalid corner index.")
        result[loop_id] = int(loops[corner_index])
    return result
