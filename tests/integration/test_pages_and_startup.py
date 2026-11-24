from __future__ import annotations

import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.core.exceptions import ImproperlyConfigured

from fuelroute.api.container import get_fuel_plan_service
from fuelroute.api.errors import problem_exception_handler
from fuelroute.core.errors import ProviderRateLimitedError
from fuelroute.startup import prepare_application
from fuelroute.stations.models import FuelStationModel, PlaceModel
from fuelroute.stations.repository import DatabasePlaceDirectory, load_station_index

if TYPE_CHECKING:
    from django.test import Client
    from pytest_django import Settings
    from rest_framework.test import APIClient


@pytest.mark.usefixtures("road_data")
def test_health_reports_the_station_count(api_client: APIClient) -> None:
    response = api_client.get("/healthz")
    assert response.status_code == HTTPStatus.OK
    assert response.json() == {"status": "ok", "stations": 5}


@pytest.mark.django_db
def test_health_without_stations_is_unavailable(api_client: APIClient) -> None:
    response = api_client.get("/healthz")
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json()["status"] == "no_stations"


def test_home_redirects_to_the_map(client: Client) -> None:
    response = client.get("/")
    assert response.status_code == HTTPStatus.FOUND
    assert response["Location"] == "/map/"


def test_map_page_uses_a_nonce_and_pinned_leaflet(client: Client) -> None:
    response = client.get("/map/?start=A&finish=B")
    assert response.status_code == HTTPStatus.OK
    policy = response["Content-Security-Policy"]
    nonce = policy.split("'nonce-", 1)[1].split("'", 1)[0]
    html = response.content.decode()
    assert f'<script nonce="{nonce}">' in html
    assert 'integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="' in html
    assert "frame-ancestors 'none'" in policy
    assert response["X-Frame-Options"] == "DENY"
    assert 'max="50.0"' in html


def test_map_page_sends_its_origin_so_tile_servers_accept_it(client: Client) -> None:
    response = client.get("/map/")
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_openapi_schema_describes_the_endpoint(client: Client) -> None:
    response = client.get("/api/schema/", HTTP_ACCEPT="application/json")
    assert response.status_code == HTTPStatus.OK
    schema = response.json()
    operation = schema["paths"]["/api/v1/fuel-plan"]["get"]
    assert operation["operationId"] == "get_fuel_plan"
    names = {parameter["name"] for parameter in operation["parameters"]}
    assert names == {"start", "finish", "start_fuel_gallons", "min_stop_saving"}
    assert {"200", "400", "422", "502", "503", "504"} <= set(operation["responses"])


@pytest.mark.usefixtures("road_data")
def test_place_directory_finds_towns_by_any_spelling() -> None:
    directory = DatabasePlaceDirectory()
    found = directory.find("WESTEND", "ks")
    assert found is not None
    assert found.label == "Westend, KS"
    assert directory.find("Westend", "NE") is None


@pytest.mark.usefixtures("road_data")
def test_station_index_loads_every_station() -> None:
    assert len(load_station_index()) == 5


@pytest.mark.usefixtures("road_data")
def test_startup_builds_the_service_once() -> None:
    prepare_application()
    assert get_fuel_plan_service() is get_fuel_plan_service()


@pytest.mark.django_db
def test_startup_without_stations_fails() -> None:
    with pytest.raises(ImproperlyConfigured, match="import_stations"):
        prepare_application()


def test_startup_without_an_api_key_fails(settings: Settings) -> None:
    settings.FUELROUTE_ORS_API_KEY = ""
    with pytest.raises(ImproperlyConfigured, match="ORS_API_KEY"):
        prepare_application()


def test_startup_with_the_debug_key_outside_debug_fails(settings: Settings) -> None:
    settings.DEBUG = False
    settings.SECRET_KEY = "django-insecure-local-development-only"
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        prepare_application()


def test_unexpected_error_becomes_an_opaque_problem(caplog: pytest.LogCaptureFixture) -> None:
    # The project logger does not propagate to the root, where caplog listens by default.
    logging.getLogger("fuelroute").addHandler(caplog.handler)
    try:
        response = problem_exception_handler(RuntimeError("database on fire"), {"view": object()})
    finally:
        logging.getLogger("fuelroute").removeHandler(caplog.handler)
    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.data["code"] == "internal_error"
    assert "database on fire" not in str(response.data)
    assert "unhandled error" in caplog.text


def test_rate_limited_provider_passes_on_the_retry_delay() -> None:
    error = ProviderRateLimitedError("quota", retry_after_seconds=42)
    response = problem_exception_handler(error, {"view": object()})
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response["Retry-After"] == "42"
    assert response.data["code"] == "provider_rate_limited"


@pytest.mark.usefixtures("road_data")
def test_models_describe_themselves() -> None:
    assert str(PlaceModel.objects.get(name="Westend")) == "Westend, KS"
    assert str(FuelStationModel.objects.get(station_id=101)) == "Station 101 (Testville, KS)"
