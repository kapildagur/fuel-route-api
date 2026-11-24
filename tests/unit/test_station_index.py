from __future__ import annotations

import pytest

from fuelroute.core.geo import Coordinate, Route
from fuelroute.core.stations import StationIndex
from tests.helpers import road_route, station


def test_station_on_the_road_gets_its_mile_marker() -> None:
    index = StationIndex([station(1, mile=123.4)])
    (found,) = index.along(road_route(300), corridor_miles=5)
    assert found.mile_marker == pytest.approx(123.4, abs=0.3)
    assert found.distance_from_route_miles == pytest.approx(0, abs=0.05)


def test_station_inside_the_corridor_is_found_with_its_offset() -> None:
    index = StationIndex([station(1, mile=50, offset_miles=4.0)])
    (found,) = index.along(road_route(300), corridor_miles=5)
    assert found.distance_from_route_miles == pytest.approx(4.0, abs=0.05)


def test_station_outside_the_corridor_is_not_found() -> None:
    index = StationIndex([station(1, mile=50, offset_miles=5.5)])
    assert index.along(road_route(300), corridor_miles=5) == []


def test_stations_come_back_in_driving_order() -> None:
    index = StationIndex([station(3, mile=250), station(1, mile=10), station(2, mile=100)])
    found = index.along(road_route(300), corridor_miles=5)
    assert [s.station.station_id for s in found] == [1, 2, 3]


def test_mile_markers_scale_to_the_provider_distance() -> None:
    geometric = road_route(300)
    longer = Route(path=geometric.path, distance_miles=330, duration_seconds=0)
    (found,) = StationIndex([station(1, mile=150)]).along(longer, corridor_miles=5)
    assert found.mile_marker == pytest.approx(165, abs=0.5)


def test_long_straight_segments_are_densified() -> None:
    # Two points 300 miles apart: without densifying, the nearest vertex is 150 miles away.
    sparse = road_route(300, points=2)
    (found,) = StationIndex([station(1, mile=150)]).along(sparse, corridor_miles=5)
    assert found.mile_marker == pytest.approx(150, abs=0.3)


def test_empty_index_finds_nothing() -> None:
    index = StationIndex([])
    assert len(index) == 0
    assert index.along(road_route(100), corridor_miles=5) == []


def test_route_of_zero_length_maps_stations_to_mile_zero() -> None:
    point = Coordinate(40.0, -100.0)
    route = Route(path=(point, point), distance_miles=0, duration_seconds=0)
    (found,) = StationIndex([station(1, mile=0)]).along(route, corridor_miles=5)
    assert found.mile_marker == 0
