from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pytest
from rest_framework.throttling import AnonRateThrottle

from fuelroute.api.errors import PROBLEM_CONTENT_TYPE
from tests.helpers import ors_geocode_payload, road_point

if TYPE_CHECKING:
    from pytest_django import Settings
    from rest_framework.test import APIClient

    from tests.conftest import FakeOpenRouteService

pytestmark = pytest.mark.usefixtures("road_data")

URL = "/api/v1/fuel-plan"


def _get(client: APIClient, **params: Any) -> Any:  # noqa: ANN401  # DRF test response
    return client.get(URL, params)


def test_plan_between_two_towns_calls_the_provider_once(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    response = _get(api_client, start="Westend, KS", finish="Eastend, KS")
    assert response.status_code == HTTPStatus.OK
    assert ors.calls == [("POST", "/v2/directions/driving-hgv/geojson")]
    assert ors.authorizations == ["test-api-key"]

    body = response.json()
    assert body["start"]["label"] == "Westend, KS"
    assert body["start"]["source"] == "place_directory"
    assert body["route"]["distance_miles"] == pytest.approx(900, abs=0.1)
    assert body["vehicle"] == {
        "tank_gallons": 50.0,
        "miles_per_gallon": 10.0,
        "range_miles": 500.0,
        "start_fuel_gallons": 50.0,
    }
    stops = body["fuel_stops"]
    assert [stop["station_id"] for stop in stops] == [102, 104]
    assert stops[0]["price_per_gallon"] == 3.199
    assert stops[0]["gallons"] == pytest.approx(10, abs=0.1)
    assert stops[1]["gallons"] == pytest.approx(30, abs=0.1)
    summary = body["summary"]
    assert summary["fuel_stop_count"] == 2
    assert summary["total_fuel_cost"] == pytest.approx(121.96, abs=0.2)
    assert summary["total_fuel_cost"] == pytest.approx(sum(stop["cost"] for stop in stops))
    assert summary["currency"] == "USD"
    assert summary["min_stop_saving"] == 5.0
    assert summary["lowest_cost_plan"]["fuel_stop_count"] == 2
    assert summary["stations_considered"] == 5
    assert body["map"]["type"] == "FeatureCollection"
    assert body["map_url"].startswith("http://testserver/map/?start=Westend")


def test_repeat_request_is_served_from_the_cache(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    first = _get(api_client, start="Westend, KS", finish="Eastend, KS")
    second = _get(api_client, start="westend, ks", finish="EASTEND, KS")
    assert first.json()["summary"] == second.json()["summary"]
    assert len(ors.calls) == 1


def test_coordinates_skip_every_lookup(api_client: APIClient, ors: FakeOpenRouteService) -> None:
    start, finish = road_point(0), road_point(900)
    response = _get(
        api_client,
        start=f"{start.latitude},{start.longitude}",
        finish=f"{finish.latitude},{finish.longitude}",
    )
    assert response.status_code == HTTPStatus.OK
    assert response.json()["start"]["source"] == "coordinates"
    assert len(ors.calls) == 1


def test_street_addresses_cost_two_geocodes_and_one_route(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    west, east = road_point(0), road_point(900)
    ors.geocode_payloads = {
        "1 Main St, Westend KS": ors_geocode_payload(west.latitude, west.longitude, "1 Main St"),
        "9 Elm St, Eastend KS": ors_geocode_payload(east.latitude, east.longitude, "9 Elm St"),
    }
    response = _get(api_client, start="1 Main St, Westend KS", finish="9 Elm St, Eastend KS")
    assert response.status_code == HTTPStatus.OK
    assert [call[1] for call in ors.calls] == [
        "/geocode/search",
        "/geocode/search",
        "/v2/directions/driving-hgv/geojson",
    ]
    assert response.json()["finish"]["source"] == "geocoder"


def test_start_fuel_and_stop_saving_change_the_plan(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    del ors
    response = _get(
        api_client,
        start="Westend, KS",
        finish="Eastend, KS",
        start_fuel_gallons="13",
        min_stop_saving="0",
    )
    body = response.json()
    assert response.status_code == HTTPStatus.OK
    assert body["vehicle"]["start_fuel_gallons"] == 13
    assert body["summary"]["min_stop_saving"] == 0
    assert (
        body["summary"]["total_fuel_cost"] == body["summary"]["lowest_cost_plan"]["total_fuel_cost"]
    )


def test_small_saving_threshold_keeps_more_stops_than_a_large_one(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    del ors
    strict = _get(api_client, start="Westend, KS", finish="Eastend, KS", min_stop_saving="0")
    relaxed = _get(api_client, start="Westend, KS", finish="Eastend, KS", min_stop_saving="500")
    assert (
        strict.json()["summary"]["fuel_stop_count"] >= relaxed.json()["summary"]["fuel_stop_count"]
    )
    assert (
        relaxed.json()["summary"]["total_fuel_cost"] >= strict.json()["summary"]["total_fuel_cost"]
    )


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"finish": "Eastend, KS"}, "start"),
        ({"start": "Westend, KS"}, "finish"),
        ({"start": "x" * 201, "finish": "Eastend, KS"}, "start"),
        (
            {"start": "Westend, KS", "finish": "Eastend, KS", "start_fuel_gallons": "-1"},
            "start_fuel_gallons",
        ),
        (
            {"start": "Westend, KS", "finish": "Eastend, KS", "start_fuel_gallons": "lots"},
            "start_fuel_gallons",
        ),
        (
            {"start": "Westend, KS", "finish": "Eastend, KS", "min_stop_saving": "-5"},
            "min_stop_saving",
        ),
        (
            {"start": "Westend, KS", "finish": "Eastend, KS", "min_stop_saving": "1e9"},
            "min_stop_saving",
        ),
    ],
)
def test_invalid_parameters_are_a_problem_response(
    api_client: APIClient, params: dict[str, str], field: str
) -> None:
    response = api_client.get(URL, params)
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response["Content-Type"] == PROBLEM_CONTENT_TYPE
    body = response.json()
    assert body["code"] == "invalid_request"
    assert field in body["errors"]


def test_start_fuel_above_the_tank_is_rejected(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    del ors
    response = _get(api_client, start="Westend, KS", finish="Eastend, KS", start_fuel_gallons="51")
    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.json()["code"] == "invalid_start_fuel"


@pytest.mark.parametrize(
    ("start", "status", "code"),
    [
        ("   ", HTTPStatus.BAD_REQUEST, "invalid_request"),
        ("95,-100", HTTPStatus.BAD_REQUEST, "invalid_location"),
        ("51.5,-0.12", HTTPStatus.UNPROCESSABLE_ENTITY, "outside_service_area"),
        ("Nowhere At All", HTTPStatus.UNPROCESSABLE_ENTITY, "location_not_found"),
    ],
)
def test_unusable_locations_are_rejected_before_routing(
    api_client: APIClient, ors: FakeOpenRouteService, start: str, status: int, code: str
) -> None:
    response = _get(api_client, start=start, finish="Eastend, KS")
    assert response.status_code == status
    assert response.json()["code"] == code
    assert ("POST", "/v2/directions/driving-hgv/geojson") not in ors.calls


def test_route_the_provider_cannot_find_is_unprocessable(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    ors.route_status = HTTPStatus.NOT_FOUND
    response = _get(api_client, start="Westend, KS", finish="Eastend, KS")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    assert response.json()["code"] == "route_not_found"


def test_route_without_fuel_in_range_reports_where_it_runs_out(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    del ors
    response = _get(api_client, start="Westend, KS", finish="Eastend, KS", start_fuel_gallons="5")
    assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
    body = response.json()
    assert body["code"] == "unreachable_segment"
    assert body["fuel_runs_out_at_mile"] == 50.0
    assert body["next_station_mile"] == pytest.approx(120, abs=0.3)


def test_unreachable_provider_is_a_bad_gateway(api_client: APIClient, settings: Settings) -> None:
    settings.FUELROUTE_ORS_BASE_URL = "http://127.0.0.1:9"
    response = _get(api_client, start="Westend, KS", finish="Eastend, KS")
    assert response.status_code == HTTPStatus.BAD_GATEWAY
    assert response.json()["code"] == "provider_unavailable"


def test_missing_api_key_is_reported_without_details(
    api_client: APIClient, settings: Settings
) -> None:
    settings.FUELROUTE_ORS_API_KEY = ""
    response = _get(api_client, start="Westend, KS", finish="Eastend, KS")
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    body = response.json()
    assert body["code"] == "provider_authentication_failed"
    assert "not configured correctly" in body["detail"]


def test_throttled_client_gets_a_problem_with_retry_after(
    api_client: APIClient, ors: FakeOpenRouteService, monkeypatch: pytest.MonkeyPatch
) -> None:
    del ors
    # DRF copies the rates onto the throttle class at import, so patch the class.
    monkeypatch.setattr(AnonRateThrottle, "THROTTLE_RATES", {"anon": "1/minute"})
    _get(api_client, start="Westend, KS", finish="Eastend, KS")
    response = _get(api_client, start="Westend, KS", finish="Eastend, KS")
    assert response.status_code == HTTPStatus.TOO_MANY_REQUESTS
    assert response["Content-Type"] == PROBLEM_CONTENT_TYPE
    assert response.json()["code"] == "throttled"
    assert "Retry-After" in response


def test_post_is_not_allowed(api_client: APIClient) -> None:
    response = api_client.post(URL, {}, format="json")
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
    assert response.json()["code"] == "method_not_allowed"
    assert response["Allow"] == "GET, HEAD, OPTIONS"


def test_blank_optional_parameters_use_the_defaults(
    api_client: APIClient, ors: FakeOpenRouteService
) -> None:
    del ors
    response = _get(
        api_client,
        start="Westend, KS",
        finish="Eastend, KS",
        start_fuel_gallons="",
        min_stop_saving="",
    )
    assert response.status_code == HTTPStatus.OK
    body = response.json()
    assert body["vehicle"]["start_fuel_gallons"] == 50.0
    assert body["summary"]["min_stop_saving"] == 5.0
