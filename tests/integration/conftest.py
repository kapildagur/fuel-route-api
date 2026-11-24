"""Fixtures for in-process tests of the Django app against a fake OpenRouteService."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from django.core.cache import caches
from rest_framework.test import APIClient

from fuelroute.api.container import reset_fuel_plan_service
from fuelroute.core.places import place_key
from fuelroute.stations.models import FuelStationModel, PlaceModel
from tests.helpers import ors_route_payload, road_point, road_route

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django import Settings

    from tests.conftest import FakeOpenRouteService

ROUTE_MILES = 900.0
"""Length of the test road; the stations below make a plan with two stops."""

STATIONS = (
    # station_id, mile, price
    (101, 120.0, "3.459"),
    (102, 300.0, "3.199"),
    (103, 480.0, "3.399"),
    (104, 600.0, "2.999"),
    (105, 800.0, "3.299"),
)


@pytest.fixture(autouse=True)
def fresh_service() -> Iterator[None]:
    """Rebuild the service and empty the caches around each test."""
    reset_fuel_plan_service()
    for alias in ("default", "routes"):
        caches[alias].clear()
    yield
    reset_fuel_plan_service()


@pytest.fixture
def api_client() -> APIClient:
    """Return a DRF test client."""
    return APIClient()


@pytest.fixture
def road_data(db: None) -> None:
    """Load the test road's stations and its two end towns into the database."""
    del db
    FuelStationModel.objects.bulk_create(
        FuelStationModel(
            station_id=station_id,
            name=f"Station {station_id}",
            address=f"I-70, EXIT {station_id}",
            city="Testville",
            state="KS",
            rack_id=1,
            price_per_gallon=Decimal(price),
            latitude=road_point(mile).latitude,
            longitude=road_point(mile).longitude,
            location_source="census_place",
        )
        for station_id, mile, price in STATIONS
    )
    for name, mile in (("Westend", 0.0), ("Eastend", ROUTE_MILES)):
        point = road_point(mile)
        PlaceModel.objects.create(
            name=name,
            state="KS",
            search_key=place_key(name),
            latitude=point.latitude,
            longitude=point.longitude,
            source="census_place",
        )


@pytest.fixture
def ors(fake_ors: FakeOpenRouteService, settings: Settings) -> FakeOpenRouteService:
    """Point the app at the fake OpenRouteService, answering with the test road."""
    fake_ors.route_payload = ors_route_payload(road_route(ROUTE_MILES, points=200))
    settings.FUELROUTE_ORS_BASE_URL = fake_ors.base_url
    return fake_ors
