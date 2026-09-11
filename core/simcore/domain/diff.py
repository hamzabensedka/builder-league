"""Diff: compute the before/after payload from two state snapshots.

The approval screen IS this diff. Computed with deepdiff over plain-data
snapshots — a real structural diff, not a narration. Pure function.
"""

from typing import Any

from deepdiff import DeepDiff


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """DeepDiff(after - before). Empty dict when snapshots are identical.

    Output is JSON-safe plain data so it can travel in API responses and be
    rendered verbatim by the UI diff view.
    """
    diff = DeepDiff(before, after, ignore_order=True, verbose_level=2)
    return diff.to_json() and diff.to_dict() or {}
