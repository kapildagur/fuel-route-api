from __future__ import annotations

import math
import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fuelroute.core.errors import InvalidLocationError, InvalidRouteError
from fuelroute.core.geo import Coordinate, Route, haversine_miles
from fuelroute.core.locations import (
    MAX_QUERY_LENGTH,
    AddressQuery,
    CoordinateQuery,
    PlaceQuery,
    is_in_united_states,
    parse_location_query,
)
from fuelroute.core.places import place_key

# ---------------------------------------------------------------- coordinates and routes


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(90.01, 0), (-90.01, 0), (0, 180.01), (0, -180.01), (math.nan, 0), (0, math.inf)],
)
def test_coordinate_outside_degree_ranges_is_rejected(latitude: float, longitude: float) -> None:
    with pytest.raises(InvalidLocationError):
        Coordinate(latitude, longitude)


def test_coordinate_on_the_boundaries_is_accepted() -> None:
    assert Coordinate(90, 180) == Coordinate(90.0, 180.0)
    assert Coordinate(-90, -180).latitude == -90


def test_haversine_matches_a_known_distance() -> None:
    # New York City to Los Angeles: 3,936 km (2,445.6 mi) along a great circle.
    new_york = Coordinate(40.7128, -74.0060)
    los_angeles = Coordinate(34.0522, -118.2437)
    assert haversine_miles(new_york, los_angeles) == pytest.approx(2445.6, abs=3)


def test_haversine_of_a_point_to_itself_is_zero() -> None:
    point = Coordinate(40, -100)
    assert haversine_miles(point, point) == 0


@given(
    st.floats(min_value=-89, max_value=89),
    st.floats(min_value=-179, max_value=179),
    st.floats(min_value=-89, max_value=89),
    st.floats(min_value=-179, max_value=179),
)
def test_haversine_is_symmetric_and_bounded(a: float, b: float, c: float, d: float) -> None:
    first, second = Coordinate(a, b), Coordinate(c, d)
    distance = haversine_miles(first, second)
    assert distance == pytest.approx(haversine_miles(second, first))
    assert 0 <= distance <= math.pi * 3958.7613 + 1e-6


def test_route_needs_two_points() -> None:
    with pytest.raises(InvalidRouteError, match="at least two points"):
        Route(path=(Coordinate(40, -100),), distance_miles=0, duration_seconds=0)


def test_route_rejects_negative_distance() -> None:
    path = (Coordinate(40, -100), Coordinate(40, -99))
    with pytest.raises(InvalidRouteError, match="must not be negative"):
        Route(path=path, distance_miles=-1, duration_seconds=0)


# ---------------------------------------------------------------- place keys


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("St. Louis", "Saint Louis"),
        ("SAINT LOUIS ", "st louis"),
        ("Mc Calla", "McCalla"),
        ("Winston-Salem", "Winston Salem"),
        ("Ft. Worth", "Fort Worth"),
        ("Mt Vernon", "Mount Vernon"),
        ("S Coffeyville", "South Coffeyville"),
        ("O'Fallon", "OFallon"),
        ("Española", "Espanola"),
    ],
)
def test_spellings_of_one_place_share_a_key(first: str, second: str) -> None:
    assert place_key(first) == place_key(second)


def test_different_places_have_different_keys() -> None:
    assert place_key("Springfield") != place_key("Springdale")


@given(st.text(alphabet=string.printable, max_size=60))
def test_place_key_is_plain_and_ignores_case_and_padding(name: str) -> None:
    key = place_key(name)
    assert all(ch.isascii() and ch.isalnum() and not ch.isupper() for ch in key)
    assert place_key(f"  {name.upper()}  ") == key


# ---------------------------------------------------------------- location queries


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("41.8781,-87.6298", CoordinateQuery(Coordinate(41.8781, -87.6298))),
        (" 41.8781 , -87.6298 ", CoordinateQuery(Coordinate(41.8781, -87.6298))),
        ("+40,-100", CoordinateQuery(Coordinate(40, -100))),
        ("Chicago, IL", PlaceQuery("Chicago", "IL")),
        ("chicago,il", PlaceQuery("chicago", "IL")),
        ("St. Louis, mo", PlaceQuery("St. Louis", "MO")),
        ("Coeur d'Alene, ID", PlaceQuery("Coeur d'Alene", "ID")),
        ("Toronto, ON", AddressQuery("Toronto, ON")),
        (
            "1600 Pennsylvania Ave NW, Washington, DC",
            AddressQuery("1600 Pennsylvania Ave NW, Washington, DC"),
        ),
        ("Chicago   Illinois", AddressQuery("Chicago Illinois")),
    ],
)
def test_query_kind_follows_its_form(text: str, expected: object) -> None:
    assert parse_location_query(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_blank_query_is_rejected(text: str) -> None:
    with pytest.raises(InvalidLocationError, match="must not be blank"):
        parse_location_query(text)


def test_query_longer_than_the_limit_is_rejected() -> None:
    with pytest.raises(InvalidLocationError, match=f"at most {MAX_QUERY_LENGTH}"):
        parse_location_query("a" * (MAX_QUERY_LENGTH + 1))


def test_query_at_the_limit_is_accepted() -> None:
    assert isinstance(parse_location_query("a" * MAX_QUERY_LENGTH), AddressQuery)


def test_coordinates_out_of_range_are_rejected() -> None:
    with pytest.raises(InvalidLocationError, match="Latitude"):
        parse_location_query("140,-100")


@pytest.mark.parametrize(
    ("latitude", "longitude", "inside"),
    [
        (41.88, -87.63, True),  # Chicago
        (24.55, -81.78, True),  # Key West
        (61.22, -149.90, True),  # Anchorage
        (21.31, -157.86, True),  # Honolulu
        (-87.63, 41.88, False),  # swapped
        (51.51, -0.13, False),  # London
        (19.43, -99.13, False),  # Mexico City
    ],
)
def test_service_area_check(latitude: float, longitude: float, *, inside: bool) -> None:
    assert is_in_united_states(Coordinate(latitude, longitude)) is inside
