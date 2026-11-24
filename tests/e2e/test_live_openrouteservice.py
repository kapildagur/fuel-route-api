"""Checks against the real OpenRouteService; run with ``make test-live`` and ORS_API_KEY set."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from fuelroute.core.geo import Coordinate
from fuelroute.providers.openrouteservice import OpenRouteServiceClient

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.environ.get("ORS_API_KEY") or os.environ.get("FUELROUTE_LIVE_TESTS") != "1",
        reason="set ORS_API_KEY and FUELROUTE_LIVE_TESTS=1 to call the real API",
    ),
]


@pytest.fixture
def client() -> Iterator[OpenRouteServiceClient]:
    client = OpenRouteServiceClient(api_key=os.environ["ORS_API_KEY"])
    yield client
    client.close()


def test_real_truck_route_from_chicago_to_dallas(client: OpenRouteServiceClient) -> None:
    route = client.route(Coordinate(41.8781, -87.6298), Coordinate(32.7767, -96.7970))
    assert 850 < route.distance_miles < 1100
    assert len(route.path) > 50


def test_real_geocoder_finds_a_us_address(client: OpenRouteServiceClient) -> None:
    location = client.geocode("1600 Pennsylvania Ave NW, Washington, DC")
    assert location is not None
    assert location.coordinate.latitude == pytest.approx(38.9, abs=0.1)
