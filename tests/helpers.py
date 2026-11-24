"""Builders shared by the tests: stations on a straight east-west road, routes and checks."""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fuelroute.core.geo import EARTH_RADIUS_MILES, Coordinate, Route
from fuelroute.core.stations import FuelStation, StationOnRoute

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from fuelroute.core.planner import FuelStop, Vehicle

FIXTURES = Path(__file__).parent / "fixtures"

ROAD_LATITUDE = 40.0
ROAD_START_LONGITUDE = -100.0
MILES_PER_DEGREE_LONGITUDE = (
    math.radians(1) * EARTH_RADIUS_MILES * math.cos(math.radians(ROAD_LATITUDE))
)


def road_point(mile: float, *, offset_miles: float = 0.0) -> Coordinate:
    """Return the point ``mile`` miles east of the road start, ``offset_miles`` north of it."""
    latitude = ROAD_LATITUDE + math.degrees(offset_miles / EARTH_RADIUS_MILES)
    return Coordinate(latitude, ROAD_START_LONGITUDE + mile / MILES_PER_DEGREE_LONGITUDE)


def road_route(length_miles: float, *, points: int = 50) -> Route:
    """Return a straight route along the road, with the provider distance equal to its length."""
    path = tuple(road_point(length_miles * i / (points - 1)) for i in range(points))
    return Route(path=path, distance_miles=length_miles, duration_seconds=length_miles * 60)


def station(  # noqa: PLR0913  # a test builder with defaults for every field
    station_id: int,
    *,
    price: str = "3.000",
    mile: float = 0.0,
    offset_miles: float = 0.0,
    name: str | None = None,
    city: str = "Testville",
    state: str = "KS",
) -> FuelStation:
    """Return a station on the test road."""
    return FuelStation(
        station_id=station_id,
        name=name or f"Station {station_id}",
        address=f"I-70, EXIT {station_id}",
        city=city,
        state=state,
        price_per_gallon=Decimal(price),
        location=road_point(mile, offset_miles=offset_miles),
    )


def on_route(station_id: int, mile: float, price: str) -> StationOnRoute:
    """Return a station already placed on a route at ``mile``."""
    return StationOnRoute(
        station=station(station_id, price=price, mile=mile),
        mile_marker=float(mile),
        distance_from_route_miles=0.0,
    )


def ors_route_payload(route: Route) -> dict[str, Any]:
    """Return an OpenRouteService GeoJSON directions response for ``route``."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[c.longitude, c.latitude] for c in route.path],
                },
                "properties": {
                    "summary": {
                        "distance": route.distance_miles * 1609.344,
                        "duration": route.duration_seconds,
                    }
                },
            }
        ],
    }


def ors_geocode_payload(latitude: float, longitude: float, label: str) -> dict[str, Any]:
    """Return an OpenRouteService geocode response with one match."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "properties": {"label": label, "country_a": "USA"},
            }
        ],
    }


def fixture_payload(name: str) -> dict[str, Any]:
    """Return a recorded route response from ``tests/fixtures``."""
    payload: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return payload


def assert_feasible(
    stops: Sequence[FuelStop],
    *,
    distance_miles: float,
    vehicle: Vehicle,
    start_fuel_gallons: float,
) -> None:
    """Drive the route with the planned purchases and fail if the tank runs dry or overflows."""
    tolerance = 1e-6
    fuel = start_fuel_gallons
    position = 0.0
    for stop in stops:
        mile = stop.station_on_route.mile_marker
        fuel -= (mile - position) / vehicle.miles_per_gallon
        assert fuel >= -tolerance, f"ran dry before mile {mile}"
        fuel += stop.gallons_exact
        assert fuel <= vehicle.tank_gallons + tolerance, f"tank overflows at mile {mile}"
        position = mile
    fuel -= (distance_miles - position) / vehicle.miles_per_gallon
    assert fuel >= -tolerance, "ran dry before the finish"


def exact_cost(stops: Iterable[FuelStop]) -> float:
    """Return the unrounded cost of the stops."""
    return sum(
        stop.gallons_exact * float(stop.station_on_route.station.price_per_gallon) for stop in stops
    )
