from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

import pytest
from django.core.cache.backends.locmem import LocMemCache
from redis.exceptions import ConnectionError as RedisConnectionError
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from fuelroute.api.caching import CachedGeocoder, CachedRoutingProvider
from fuelroute.api.geojson import fuel_plan_feature_collection
from fuelroute.api.throttling import FailOpenAnonRateThrottle
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
    collection = fuel_plan_feature_collection(plan, tolerance_meters=50)
    kinds = [feature["properties"]["kind"] for feature in collection["features"]]
    assert kinds == ["route", "start", "finish", "fuel_stop"]
    line = collection["features"][0]["geometry"]
    assert line["type"] == "LineString"
    # The test road is straight, so its 50 points simplify to the two ends.
    assert line["coordinates"] == [[-100.0, 40.0], [round(road_point(600).longitude, 5), 40.0]]
    assert collection["features"][0]["properties"]["tolerance_meters"] == 50
    stop_properties = collection["features"][3]["properties"]
    assert stop_properties["sequence"] == 1
    assert stop_properties["station_id"] == 7
    assert stop_properties["cost"] == 32.5
    assert stop_properties["mile_marker"] == 300.0


def test_tolerance_of_zero_returns_the_full_route_line() -> None:
    route = road_route(600)
    plan = FuelPlan(
        start=ResolvedLocation("A", road_point(0), LocationSource.COORDINATES),
        finish=ResolvedLocation("B", road_point(600), LocationSource.COORDINATES),
        route=route,
        vehicle=Vehicle(),
        start_fuel_gallons=50,
        min_stop_saving=Decimal(5),
        stop_plan=StopPlan(stops=(), lowest_cost=Decimal("0.00"), lowest_cost_stop_count=0),
        stations_considered=0,
    )
    collection = fuel_plan_feature_collection(plan, tolerance_meters=0)
    assert len(collection["features"][0]["geometry"]["coordinates"]) == len(route.path)


class FailingCache(LocMemCache):
    """A cache whose store is down, as when Redis cannot be reached."""

    def get(self, *_args: object, **_kwargs: object) -> object:
        raise RedisConnectionError("connection refused")

    def set(self, *_args: object, **_kwargs: object) -> None:
        raise RedisConnectionError("connection refused")


@pytest.fixture
def failing_cache() -> FailingCache:
    return FailingCache("failing", {})


def test_packed_route_comes_back_equal(cache: LocMemCache) -> None:
    route = road_route(300, points=40)
    provider = CountingRouting()
    cached = CachedRoutingProvider(provider, cache, namespace="ors:test", timeout_seconds=60)
    key_start, key_finish = route.path[0], route.path[-1]
    provider_route = cached.route(key_start, key_finish)
    assert cached.route(key_start, key_finish) == provider_route
    assert provider.calls == 1


def test_value_in_an_old_format_is_a_miss(cache: LocMemCache) -> None:
    provider = CountingRouting()
    cached = CachedRoutingProvider(provider, cache, namespace="ors:test", timeout_seconds=60)
    start, finish = Coordinate(40, -100), Coordinate(41, -99)
    key = "route:v2:ors:test:40.00000,-100.00000:41.00000,-99.00000"
    cache.set(key, Route(path=(start, finish), distance_miles=1, duration_seconds=1))
    cached.route(start, finish)
    assert provider.calls == 1


def test_route_cache_outage_falls_back_to_the_provider(
    failing_cache: FailingCache, caplog: pytest.LogCaptureFixture
) -> None:
    provider = CountingRouting()
    cached = CachedRoutingProvider(
        provider, failing_cache, namespace="ors:test", timeout_seconds=60
    )
    logging.getLogger("fuelroute").addHandler(caplog.handler)
    try:
        route = cached.route(Coordinate(40, -100), Coordinate(41, -99))
    finally:
        logging.getLogger("fuelroute").removeHandler(caplog.handler)
    assert route.distance_miles == 1
    assert provider.calls == 1
    assert "cache read failed" in caplog.text
    assert "cache write failed" in caplog.text


def test_geocode_cache_outage_falls_back_to_the_geocoder(failing_cache: FailingCache) -> None:
    place = ResolvedLocation("1 Main St", Coordinate(38, -98), LocationSource.GEOCODER)
    geocoder = CountingGeocoder({"1 Main St": place})
    cached = CachedGeocoder(geocoder, failing_cache, timeout_seconds=60)
    assert cached.geocode("1 Main St") == place
    assert geocoder.calls == ["1 Main St"]


def test_rate_limit_lets_requests_through_when_its_store_fails(
    failing_cache: FailingCache,
) -> None:
    throttle = FailOpenAnonRateThrottle()
    throttle.cache = failing_cache
    request = Request(APIRequestFactory().get("/api/v1/fuel-plan"))
    assert throttle.allow_request(request, APIView()) is True
