"""Coordinates, great-circle distances and driving routes, measured in miles."""

from __future__ import annotations

import math
from dataclasses import dataclass

from fuelroute.core.errors import InvalidLocationError, InvalidRouteError

__all__ = ["EARTH_RADIUS_MILES", "Coordinate", "Route", "haversine_miles"]

EARTH_RADIUS_MILES = 3958.7613
"""Mean Earth radius (IUGG), so distances come out in statute miles."""

_MAX_LATITUDE = 90.0
_MAX_LONGITUDE = 180.0
_MIN_PATH_POINTS = 2


@dataclass(frozen=True, slots=True)
class Coordinate:
    """A WGS 84 point in decimal degrees."""

    latitude: float
    longitude: float

    def __post_init__(self) -> None:
        """Reject values outside the valid degree ranges."""
        if not (math.isfinite(self.latitude) and abs(self.latitude) <= _MAX_LATITUDE):
            msg = f"Latitude {self.latitude!r} is outside -90 to 90."
            raise InvalidLocationError(msg)
        if not (math.isfinite(self.longitude) and abs(self.longitude) <= _MAX_LONGITUDE):
            msg = f"Longitude {self.longitude!r} is outside -180 to 180."
            raise InvalidLocationError(msg)


def haversine_miles(a: Coordinate, b: Coordinate) -> float:
    """Return the great-circle distance between two points in miles."""
    lat1, lat2 = math.radians(a.latitude), math.radians(b.latitude)
    dlat = lat2 - lat1
    dlon = math.radians(b.longitude - a.longitude)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(min(1.0, math.sqrt(h)))


@dataclass(frozen=True, slots=True)
class Route:
    """A driving route: its path and the distance and time the provider reports."""

    path: tuple[Coordinate, ...]
    distance_miles: float
    duration_seconds: float

    def __post_init__(self) -> None:
        """Reject a path without two points or a negative distance or duration."""
        if len(self.path) < _MIN_PATH_POINTS:
            msg = f"A route path needs at least two points, got {len(self.path)}."
            raise InvalidRouteError(msg)
        if self.distance_miles < 0 or self.duration_seconds < 0:
            msg = (
                f"Route distance {self.distance_miles!r} and duration "
                f"{self.duration_seconds!r} must not be negative."
            )
            raise InvalidRouteError(msg)
