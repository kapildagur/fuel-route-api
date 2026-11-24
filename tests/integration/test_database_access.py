"""How many queries each request runs, and that they use the indexes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.db import connection

from fuelroute.api.container import get_fuel_plan_service
from fuelroute.core.places import place_key
from fuelroute.stations.models import PlaceModel
from fuelroute.stations.repository import DatabasePlaceDirectory, load_station_index
from tests.helpers import road_point

if TYPE_CHECKING:
    from pytest_django import DjangoAssertNumQueries
    from rest_framework.test import APIClient

    from tests.conftest import FakeOpenRouteService

pytestmark = pytest.mark.usefixtures("road_data")


@pytest.fixture
def warm_service(ors: FakeOpenRouteService) -> FakeOpenRouteService:
    """Build the service first, as server start-up does, so requests are measured alone."""
    get_fuel_plan_service()
    return ors


def test_plan_between_two_towns_runs_two_queries(
    api_client: APIClient,
    warm_service: FakeOpenRouteService,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    del warm_service
    with django_assert_num_queries(2):
        response = api_client.get(
            "/api/v1/fuel-plan", {"start": "Westend, KS", "finish": "Eastend, KS"}
        )
    assert response.status_code == 200


def test_plan_between_coordinates_runs_no_query(
    api_client: APIClient,
    warm_service: FakeOpenRouteService,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    del warm_service
    start, finish = road_point(0), road_point(900)
    with django_assert_num_queries(0):
        response = api_client.get(
            "/api/v1/fuel-plan",
            {
                "start": f"{start.latitude},{start.longitude}",
                "finish": f"{finish.latitude},{finish.longitude}",
            },
        )
    assert response.status_code == 200


def test_health_check_runs_no_query(
    api_client: APIClient,
    warm_service: FakeOpenRouteService,
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    del warm_service
    with django_assert_num_queries(0):
        assert api_client.get("/healthz").status_code == 200


def test_station_index_loads_in_one_query(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    with django_assert_num_queries(1) as captured:
        index = load_station_index()
    assert len(index) == 5
    sql = captured.captured_queries[0]["sql"]
    assert "rack_id" not in sql
    assert "location_source" not in sql


def test_town_lookup_selects_four_columns_without_sorting(
    django_assert_num_queries: DjangoAssertNumQueries,
) -> None:
    with django_assert_num_queries(1) as captured:
        assert DatabasePlaceDirectory().find("Westend", "KS") is not None
    sql = captured.captured_queries[0]["sql"].upper()
    assert "ORDER BY" not in sql
    assert '"SOURCE"' not in sql


def test_town_lookup_is_served_by_the_unique_index() -> None:
    query = PlaceModel.objects.filter(state="KS", search_key=place_key("Westend"))
    if connection.vendor == "postgresql":
        # With a handful of rows PostgreSQL prefers a sequential scan; forbid it to show
        # that the index can serve the lookup, as it does on the full table.
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL enable_seqscan = off")
        assert "Index Scan using place_unique_key" in query.explain()
    else:
        # SQLite backs the unique constraint with an automatic index of its own name.
        assert "SEARCH place USING INDEX" in query.explain()
