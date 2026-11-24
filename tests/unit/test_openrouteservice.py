from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from fuelroute.core.errors import (
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RouteNotFoundError,
    RouteTooLongError,
)
from fuelroute.core.geo import Coordinate
from fuelroute.core.locations import LocationSource
from fuelroute.providers.openrouteservice import OpenRouteServiceClient
from tests.helpers import ors_geocode_payload, ors_route_payload, road_route

if TYPE_CHECKING:
    from collections.abc import Callable

START = Coordinate(41.8781, -87.6298)
FINISH = Coordinate(32.7767, -96.7970)


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fuelroute.providers.openrouteservice._RETRY_DELAY_SECONDS", 0)


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
    **options: Any,  # noqa: ANN401  # forwards client options
) -> OpenRouteServiceClient:
    return OpenRouteServiceClient(
        api_key="secret-key", transport=httpx.MockTransport(handler), **options
    )


def _json(status: int, body: Any, **headers: str) -> httpx.Response:  # noqa: ANN401  # any JSON body
    return httpx.Response(status, json=body, headers=headers)


def test_route_request_carries_the_key_profile_and_points() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json(200, ors_route_payload(road_route(100)))

    route = _client(handler, profile="driving-car").route(START, FINISH)
    (request,) = seen
    assert request.url.path == "/v2/directions/driving-car/geojson"
    assert request.headers["Authorization"] == "secret-key"
    # The GeoJSON endpoint answers 406 unless the client accepts application/geo+json.
    assert "application/geo+json" in request.headers["Accept"]
    body = json.loads(request.content)
    assert body["coordinates"] == [[-87.6298, 41.8781], [-96.797, 32.7767]]
    assert body["geometry_simplify"] is True
    assert route.distance_miles == pytest.approx(100)
    assert len(route.path) == 50


def test_route_without_a_summary_has_zero_length() -> None:
    payload = ors_route_payload(road_route(10))
    payload["features"][0]["properties"] = {}
    route = _client(lambda _: _json(200, payload)).route(START, FINISH)
    assert route.distance_miles == 0
    assert route.duration_seconds == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"features": []},
        {"features": [{"geometry": {"coordinates": [[1, 2]]}, "properties": {}}]},
        {"features": [{"geometry": {"coordinates": [["a", "b"], [1, 2]]}, "properties": {}}]},
        {"features": [{"geometry": {"coordinates": [[1, 200], [1, 2]]}, "properties": {}}]},
    ],
)
def test_unreadable_route_is_a_provider_error(payload: dict[str, Any]) -> None:
    with pytest.raises(ProviderError, match="cannot read"):
        _client(lambda _: _json(200, payload)).route(START, FINISH)


def test_body_that_is_not_a_json_object_is_a_provider_error() -> None:
    with pytest.raises(ProviderError, match="not a JSON object"):
        _client(lambda _: httpx.Response(200, text="<html>")).route(START, FINISH)


@pytest.mark.parametrize(
    ("status", "body", "error", "message"),
    [
        (
            401,
            {"error": "Access to this API has been disallowed"},
            ProviderAuthenticationError,
            "rejected the API key",
        ),
        (403, {}, ProviderAuthenticationError, "rejected the API key"),
        (
            404,
            {"error": {"code": 2010, "message": "Could not find routable point"}},
            RouteNotFoundError,
            "routable point",
        ),
        (
            404,
            {"error": {"code": 2009, "message": "Route could not be found"}},
            RouteNotFoundError,
            "No drivable route",
        ),
        (
            400,
            {"error": {"code": 2004, "message": "exceeds 6000000.0 meters"}},
            RouteTooLongError,
            "longer than OpenRouteService allows",
        ),
        (
            400,
            {"error": {"code": 2003, "message": "Parameter invalid"}},
            ProviderError,
            "refused the request",
        ),
        (
            500,
            {"error": {"code": 2099, "message": "Unknown"}},
            ProviderUnavailableError,
            "HTTP 500",
        ),
    ],
)
def test_error_statuses_map_to_domain_errors(
    status: int, body: dict[str, Any], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        _client(lambda _: _json(status, body)).route(START, FINISH)


def test_quota_error_carries_the_retry_delay() -> None:
    client = _client(lambda _: _json(429, {"error": "Rate limit"}, **{"Retry-After": "30"}))
    with pytest.raises(ProviderRateLimitedError) as caught:
        client.route(START, FINISH)
    assert caught.value.retry_after_seconds == 30


def test_quota_error_without_a_retry_delay() -> None:
    with pytest.raises(ProviderRateLimitedError) as caught:
        _client(lambda _: _json(429, {})).route(START, FINISH)
    assert caught.value.retry_after_seconds is None


def test_gateway_error_is_retried_once() -> None:
    answers = iter([_json(503, {}), _json(200, ors_route_payload(road_route(10)))])
    route = _client(lambda _: next(answers)).route(START, FINISH)
    assert route.distance_miles == pytest.approx(10)


def test_gateway_error_twice_is_unavailable() -> None:
    calls: list[int] = []

    def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return _json(502, {})

    with pytest.raises(ProviderUnavailableError):
        _client(handler).route(START, FINISH)
    assert len(calls) == 2


def test_timeout_is_retried_then_reported() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ProviderTimeoutError, match="did not answer in time"):
        _client(handler).route(START, FINISH)
    assert len(calls) == 2


def test_connection_failure_is_retried_then_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProviderUnavailableError, match="could not be reached: ConnectError"):
        _client(handler, max_attempts=1).route(START, FINISH)


def test_connection_failure_then_success_returns_the_route() -> None:
    attempts = iter([True, False])

    def handler(request: httpx.Request) -> httpx.Response:
        if next(attempts):
            raise httpx.ConnectError("refused", request=request)
        return _json(200, ors_route_payload(road_route(10)))

    assert _client(handler).route(START, FINISH).distance_miles == pytest.approx(10)


def test_timeout_then_success_returns_the_route() -> None:
    attempts = iter([True, False])

    def handler(request: httpx.Request) -> httpx.Response:
        if next(attempts):
            raise httpx.ConnectTimeout("slow", request=request)
        return _json(200, ors_route_payload(road_route(10)))

    assert _client(handler).route(START, FINISH).distance_miles == pytest.approx(10)


def test_missing_api_key_is_refused_at_construction() -> None:
    with pytest.raises(ProviderAuthenticationError, match="API key is required"):
        OpenRouteServiceClient(api_key="")


def test_geocode_asks_for_one_us_match() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _json(200, ors_geocode_payload(38.88, -99.33, "Hays, KS, USA"))

    location = _client(handler).geocode("Hays Kansas")
    (request,) = seen
    assert request.url.path == "/geocode/search"
    assert request.url.params["text"] == "Hays Kansas"
    assert request.url.params["boundary.country"] == "USA"
    assert request.url.params["size"] == "1"
    assert location is not None
    assert location.label == "Hays, KS, USA"
    assert location.coordinate == Coordinate(38.88, -99.33)
    assert location.source is LocationSource.GEOCODER


def test_geocode_without_matches_is_none() -> None:
    assert _client(lambda _: _json(200, {"features": []})).geocode("Atlantis") is None
    assert _client(lambda _: _json(200, {})).geocode("Atlantis") is None


def test_geocode_without_a_label_uses_the_coordinates() -> None:
    payload = ors_geocode_payload(38.88, -99.33, "")
    location = _client(lambda _: _json(200, payload)).geocode("somewhere")
    assert location is not None
    assert location.label == "38.88,-99.33"


def test_unreadable_geocode_is_a_provider_error() -> None:
    payload = {"features": [{"geometry": {"coordinates": ["x"]}}]}
    with pytest.raises(ProviderError, match="geocode result"):
        _client(lambda _: _json(200, payload)).geocode("somewhere")


def test_close_releases_the_connections() -> None:
    client = _client(lambda _: _json(200, {}))
    client.close()
    with pytest.raises(RuntimeError):
        client.geocode("anything")
