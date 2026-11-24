"""Speed budget for NFR-01: planning a cross-country route, provider call excluded."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from fuelroute.core.geo import Coordinate, Route
from fuelroute.core.places import place_key
from fuelroute.core.planner import StopPlan, Vehicle, plan_fuel_stops
from fuelroute.core.stations import FuelStation, StationIndex
from fuelroute.data.fuel_prices import read_fuel_prices, select_us_stations
from fuelroute.data.gazetteer import read_places
from tests.helpers import fixture_payload

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

DATA = Path(__file__).resolve().parents[2] / "data"
BUDGET_SECONDS = 0.100
"""NFR-01: matching and planning take at most 100 ms for a 2,800-mile route."""


@pytest.fixture(scope="module")
def index() -> StationIndex:
    places = {place.key: place for place in read_places(DATA / "places.csv")}
    stations = []
    for record in select_us_stations(read_fuel_prices(DATA / "fuel-prices.csv")).records:
        place = places[(place_key(record.city), record.state)]
        stations.append(
            FuelStation(
                station_id=record.station_id,
                name=record.name,
                address=record.address,
                city=record.city,
                state=record.state,
                price_per_gallon=record.price_per_gallon,
                location=Coordinate(place.latitude, place.longitude),
            )
        )
    return StationIndex(stations)


@pytest.fixture(scope="module")
def cross_country() -> Route:
    feature = fixture_payload("route-new-york-los-angeles.json")["features"][0]
    path = tuple(Coordinate(lat, lon) for lon, lat in feature["geometry"]["coordinates"])
    summary = feature["properties"]["summary"]
    return Route(path, summary["distance"] / 1609.344, summary["duration"])


def test_cross_country_plan_fits_the_budget(
    benchmark: BenchmarkFixture, index: StationIndex, cross_country: Route
) -> None:
    def plan() -> StopPlan:
        nearby = index.along(cross_country, corridor_miles=5)
        return plan_fuel_stops(
            nearby,
            distance_miles=cross_country.distance_miles,
            vehicle=Vehicle(),
            start_fuel_gallons=50,
            min_stop_saving=Decimal(5),
        )

    result = benchmark(plan)
    assert len(result.stops) >= 5
    if benchmark.stats is not None:
        assert benchmark.stats.stats.mean < BUDGET_SECONDS
