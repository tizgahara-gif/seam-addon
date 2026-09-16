"""Pure planning helpers for seam-state mirroring."""

from __future__ import annotations


def seam_state_assignments(mapping, source_states, midpoints, direction,
                           tolerance, selected=()):
    """Plan writes using only seam states captured before synchronization."""
    selected = set(selected)
    pairs = {
        (min(source, target), max(source, target))
        for source, target in mapping.items()
        if source != target
    }
    assignments = {}
    conflicts = 0
    for first, second in sorted(pairs):
        if direction == "SELECTED":
            first_selected = first in selected
            second_selected = second in selected
            if first_selected and second_selected:
                if source_states[first] != source_states[second]:
                    conflicts += 1
                continue
            if first_selected:
                assignments[second] = source_states[first]
            elif second_selected:
                assignments[first] = source_states[second]
            continue

        wanted_positive = direction == "POSITIVE"
        candidates = (
            edge for edge in (first, second)
            if ((midpoints[edge] > tolerance) == wanted_positive)
            and abs(midpoints[edge]) > tolerance
        )
        source = next(candidates, None)
        if source is not None:
            target = second if source == first else first
            assignments[target] = source_states[source]
    return assignments, conflicts
