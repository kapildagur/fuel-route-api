from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from django.core.cache.backends.locmem import LocMemCache

from fuelroute.api.caching import CachedGeocoder, CachedRoutingProvider
from fuelroute.api.geojson import fuel_plan_feature_collection
from fuelroute.core.geo import Coordinate, Route
from fuelroute.core.locations import LocationSource, ResolvedLocation
from fuelroute.core.planner import FuelStop, StopPlan, Vehicle
from fuelroute.core.service import FuelPlan
from tests.helpers import on_route, road_point, road_route


@pytest.fixture
def cache() -> LocMemCache:
    backend = LocMemCache("unit-test", {"OPTIONS": {"MAX_ENTRIES": 10}})
    backend.clear()
    return backend


@dataclass
class CountingRouting:
    calls: int = 0

    def route(self, start: Coordinate, finish: Coordinate) -> Route:
        self.calls += 1
        return Route(path=(start, finish), distance_miles=1, duration_seconds=60)


@dataclass
class CountingGeocoder:
    answers: dict[str, ResolvedLocation] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def geocode(self, text: str) -> ResolvedLocation | None:
        self.calls.append(text)
        return self.answers.get(text)


def test_same_points_are_routed_once(cache: LocMemCache) -> None:
    provider = CountingRouting()
    cached = CachedRoutingProvider(provider, cache, namespace="ors:test", timeout_seconds=60)
    first = cached.route(Coordinate(40, -100), Coordinate(41, -99))
    second = cached.route(Coordinate(40.000001, -100), Coordinate(41, -99))
    assert first == second
    assert provider.calls == 1


def test_different_points_or_profiles_are_routed_separately(cache: LocMemCache) -> None:
    provider = CountingRouting()
    car = CachedRoutingProvider(provider, cache, namespace="ors:car", timeout_seconds=60)
    truck = CachedRoutingProvider(provider, cache, namespace="ors:hgv", timeout_seconds=60)
    car.route(Coordinate(40, -100), Coordinate(41, -99))
    car.route(Coordinate(40, -100), Coordinate(42, -99))
    truck.route(Coordinate(40, -100), Coordinate(41, -99))
    assert provider.calls == 3


def test_geocoding_answers_are_cached_ignoring_case_and_spacing(cache: LocMemCache) -> None:
    place = ResolvedLocation("1 Main St", Coordinate(38, -98), LocationSource.GEOCODER)
    geocoder = CountingGeocoder({"1 Main St": place})
    cached = CachedGeocoder(geocoder, cache, timeout_seconds=60)
    assert cached.geocode("1 Main St") == place
    assert cached.geocode("1  MAIN st ") == place
    assert geocoder.calls == ["1 Main St"]


def test_geocoding_misses_are_cached_too(cache: LocMemCache) -> None:
    geocoder = CountingGeocoder()
    cached = CachedGeocoder(geocoder, cache, timeout_seconds=60)
    assert cached.geocode("Atlantis") is None
    assert cached.geocode("atlantis") is None
    assert geocoder.calls == ["Atlantis"]


def test_feature_collection_holds_route_ends_and_numbered_stops() -> None:
    route = road_route(600)
    stop = FuelStop(on_route(7, 300, "3.25"), 10.0)
    plan = FuelPlan(
        start=ResolvedLocation("A", road_point(0), LocationSource.COORDINATES),
        finish=ResolvedLocation("B", road_point(600), LocationSource.COORDINATES),
        route=route,
        vehicle=Vehicle(),
        start_fuel_gallons=50,
        min_stop_saving=Decimal(5),
        stop_plan=StopPlan(stops=(stop,), lowest_cost=Decimal("32.50"), lowest_cost_stop_count=1),
        stations_considered=1,
    )
    collection = fuel_plan_feature_collection(plan)
    kinds = [feature["properties"]["kind"] for feature in collection["features"]]
    assert kinds == ["route", "start", "finish", "fuel_stop"]
    line = collection["features"][0]["geometry"]
    assert line["type"] == "LineString"
    assert line["coordinates"][0] == [-100.0, 40.0]
    stop_properties = collection["features"][3]["properties"]
    assert stop_properties["sequence"] == 1
    assert stop_properties["station_id"] == 7
    assert stop_properties["cost"] == 32.5
    assert stop_properties["mile_marker"] == 300.0
