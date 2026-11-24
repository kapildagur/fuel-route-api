"""Line simplification for display: fewer points, every dropped point within a tolerance."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from fuelroute.core.geo import Coordinate

__all__ = ["simplify_path"]

_EARTH_RADIUS_METERS = 6_371_008.8
_MIN_POINTS = 3


def simplify_path(path: Sequence[Coordinate], *, tolerance_meters: float) -> tuple[Coordinate, ...]:
    """Return the path with points removed while each stays within ``tolerance_meters``.

    This is the Ramer-Douglas-Peucker algorithm, measuring each point against the chord
    as a segment. The ends are always kept, and a tolerance of zero or less returns the
    path unchanged. Distances are measured in a
    plane tangent at the path's mean latitude, which is accurate to well under one
    percent for the short chords a road route produces.
    """
    if tolerance_meters <= 0 or len(path) < _MIN_POINTS:
        return tuple(path)
    latitudes = np.fromiter((c.latitude for c in path), dtype=np.float64, count=len(path))
    longitudes = np.fromiter((c.longitude for c in path), dtype=np.float64, count=len(path))
    keep = _keep_mask(latitudes, longitudes, tolerance_meters)
    return tuple(point for point, kept in zip(path, keep.tolist(), strict=True) if kept)


def _keep_mask(
    latitudes: NDArray[np.float64], longitudes: NDArray[np.float64], tolerance: float
) -> NDArray[np.bool_]:
    """Split every open segment at its farthest point in one pass, until none is too far.

    Each pass works on arrays instead of one Python step per split, and points in
    segments that are already within tolerance drop out, so later passes shrink.
    """
    scale = np.cos(np.radians(latitudes.mean()))
    x = np.radians(longitudes) * _EARTH_RADIUS_METERS * scale
    y = np.radians(latitudes) * _EARTH_RADIUS_METERS
    keep = np.zeros(latitudes.size, dtype=bool)
    keep[[0, -1]] = True
    open_points = np.arange(1, latitudes.size - 1)
    while open_points.size:
        kept = np.flatnonzero(keep)
        segment = np.searchsorted(kept, open_points, side="right") - 1
        start, end = kept[segment], kept[segment + 1]
        dx, dy = x[end] - x[start], y[end] - y[start]
        px, py = x[open_points] - x[start], y[open_points] - y[start]
        # Distance to the chord as a segment, not to its infinite line, so a road that
        # doubles back along itself keeps its turning point.
        length_squared = dx * dx + dy * dy
        along = np.clip(
            (px * dx + py * dy) / np.where(length_squared > 0, length_squared, 1.0), 0.0, 1.0
        )
        distance = np.hypot(px - along * dx, py - along * dy)
        # open_points is sorted, so each segment's points form one run.
        run_starts = np.flatnonzero(np.r_[True, segment[1:] != segment[:-1]])
        run_of_point = np.cumsum(np.r_[False, segment[1:] != segment[:-1]])
        farthest = np.maximum.reduceat(distance, run_starts)
        splits = farthest[run_of_point] > tolerance
        candidates = np.flatnonzero(splits & (distance == farthest[run_of_point]))
        # Several points can tie for farthest in one run; split at the first only.
        _, first = np.unique(run_of_point[candidates], return_index=True)
        keep[open_points[candidates[first]]] = True
        open_points = open_points[splits & ~keep[open_points]]
    return keep
