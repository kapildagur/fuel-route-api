"""Location queries as the caller writes them, and the points they resolve to."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from fuelroute.core.errors import InvalidLocationError
from fuelroute.core.geo import Coordinate

__all__ = [
    "MAX_QUERY_LENGTH",
    "US_STATE_CODES",
    "AddressQuery",
    "CoordinateQuery",
    "LocationQuery",
    "LocationSource",
    "PlaceQuery",
    "ResolvedLocation",
    "is_in_united_states",
    "parse_location_query",
]

MAX_QUERY_LENGTH = 200
"""Longest query accepted; a US street address with city and state fits in far less."""

US_STATE_CODES = frozenset(
    (
        *("AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI", "IA"),
        *("ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS"),
        *("MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA"),
        *("RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY"),
    )
)
"""USPS codes of the 50 states and the District of Columbia."""

# Boxes around the lower 48 states, Alaska and Hawaii. They are coarse on purpose:
# the routing provider rejects a point it cannot reach by road, and this check only
# stops obvious mistakes, such as swapped latitude and longitude, before any call.
_US_BOUNDS = (
    (24.3, 49.5, -125.0, -66.8),
    (51.0, 71.6, -179.2, -129.9),
    (18.8, 22.4, -160.3, -154.7),
)

_COORDINATES = re.compile(r"^\s*([-+]?\d{1,3}(?:\.\d+)?)\s*,\s*([-+]?\d{1,3}(?:\.\d+)?)\s*$")
_PLACE = re.compile(r"^\s*([A-Za-z][A-Za-z .'\-]{0,79}?)\s*,\s*([A-Za-z]{2})\s*$")


@dataclass(frozen=True, slots=True)
class CoordinateQuery:
    """A query written as ``latitude,longitude``."""

    coordinate: Coordinate


@dataclass(frozen=True, slots=True)
class PlaceQuery:
    """A query written as ``City, ST`` with a USPS state code."""

    name: str
    state: str


@dataclass(frozen=True, slots=True)
class AddressQuery:
    """Any other query, such as a street address, left to the geocoder."""

    text: str


type LocationQuery = CoordinateQuery | PlaceQuery | AddressQuery


class LocationSource(StrEnum):
    """Where a resolved location came from."""

    COORDINATES = "coordinates"
    PLACE_DIRECTORY = "place_directory"
    GEOCODER = "geocoder"


@dataclass(frozen=True, slots=True)
class ResolvedLocation:
    """A point with a readable label and the source that produced it."""

    label: str
    coordinate: Coordinate
    source: LocationSource


def parse_location_query(text: str) -> LocationQuery:
    """Return the kind of query ``text`` is.

    Raises:
        InvalidLocationError: the text is blank or longer than ``MAX_QUERY_LENGTH``,
            or looks like coordinates that are out of range.
    """
    stripped = " ".join(text.split())
    if not stripped:
        msg = "A location must not be blank."
        raise InvalidLocationError(msg)
    if len(stripped) > MAX_QUERY_LENGTH:
        msg = f"A location must be at most {MAX_QUERY_LENGTH} characters, got {len(stripped)}."
        raise InvalidLocationError(msg)

    if match := _COORDINATES.match(stripped):
        latitude, longitude = float(match.group(1)), float(match.group(2))
        return CoordinateQuery(Coordinate(latitude, longitude))
    if (match := _PLACE.match(stripped)) and match.group(2).upper() in US_STATE_CODES:
        return PlaceQuery(name=match.group(1), state=match.group(2).upper())
    return AddressQuery(stripped)


def is_in_united_states(coordinate: Coordinate) -> bool:
    """Return whether the point lies in the boxes around the lower 48, Alaska or Hawaii."""
    return any(
        south <= coordinate.latitude <= north and west <= coordinate.longitude <= east
        for south, north, west, east in _US_BOUNDS
    )
