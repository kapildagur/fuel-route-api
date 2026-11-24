from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fuelroute.core.geo import Coordinate
from fuelroute.core.simplify import simplify_path
from tests.helpers import road_point

EARTH_RADIUS_METERS = 6_371_008.8


def _project(points: list[Coordinate], mean_latitude: float) -> list[tuple[float, float]]:
    scale = math.cos(math.radians(mean_latitude))
    return [
        (
            math.radians(p.longitude) * EARTH_RADIUS_METERS * scale,
            math.radians(p.latitude) * EARTH_RADIUS_METERS,
        )
        for p in points
    ]


def _distance_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    (px, py), (ax, ay), (bx, by) = point, start, end
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def test_collinear_points_reduce_to_the_ends() -> None:
    path = tuple(road_point(mile) for mile in range(0, 101, 5))
    assert simplify_path(path, tolerance_meters=50) == (path[0], path[-1])


def test_a_detour_beyond_the_tolerance_is_kept() -> None:
    path = (road_point(0), road_point(50, offset_miles=0.5), road_point(100))
    assert simplify_path(path, tolerance_meters=50) == path


def test_a_detour_within_the_tolerance_is_dropped() -> None:
    path = (road_point(0), road_point(50, offset_miles=0.02), road_point(100))
    assert simplify_path(path, tolerance_meters=50) == (path[0], path[-1])


@pytest.mark.parametrize("tolerance", [0, -1])
def test_tolerance_of_zero_or_less_keeps_every_point(tolerance: float) -> None:
    path = tuple(road_point(mile) for mile in range(10))
    assert simplify_path(path, tolerance_meters=tolerance) == path


def test_paths_of_two_points_are_returned_unchanged() -> None:
    path = (road_point(0), road_point(10))
    assert simplify_path(path, tolerance_meters=50) == path


def test_repeated_points_are_handled() -> None:
    point = road_point(0)
    path = (point, point, road_point(50, offset_miles=1), point)
    simplified = simplify_path(path, tolerance_meters=50)
    assert simplified[0] == point
    assert simplified[-1] == point
    assert road_point(50, offset_miles=1) in simplified


coordinates = st.builds(
    Coordinate,
    st.floats(min_value=30.0, max_value=31.0),
    st.floats(min_value=-100.0, max_value=-99.0),
)


@settings(max_examples=200, deadline=None)
@given(st.lists(coordinates, min_size=3, max_size=60), st.floats(min_value=1, max_value=5000))
def test_every_dropped_point_stays_within_the_tolerance(
    path: list[Coordinate], tolerance: float
) -> None:
    simplified = simplify_path(path, tolerance_meters=tolerance)
    assert simplified[0] == path[0]
    assert simplified[-1] == path[-1]
    remaining = iter(path)
    assert all(point in remaining for point in simplified), "result must be a subsequence"

    mean_latitude = sum(p.latitude for p in path) / len(path)
    original = _project(path, mean_latitude)
    kept = _project(list(simplified), mean_latitude)
    for point in original:
        nearest = min(
            _distance_to_segment(point, kept[i], kept[i + 1]) for i in range(len(kept) - 1)
        )
        assert nearest <= tolerance * 1.0001 + 1e-6


def test_a_turnaround_on_the_same_line_is_kept() -> None:
    # Mile 100 is on the line through miles 0 and 60, but 40 miles past the chord's end.
    path = (road_point(0), road_point(100), road_point(60))
    assert simplify_path(path, tolerance_meters=50) == path
