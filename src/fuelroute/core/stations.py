"""Fuel stations and the in-memory index that finds the ones along a route."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import cKDTree

from fuelroute.core.geo import EARTH_RADIUS_MILES

if TYPE_CHECKING:
    from collections.abc import Iterable
    from decimal import Decimal

    from numpy.typing import NDArray

    from fuelroute.core.geo import Coordinate, Route

__all__ = ["FuelStation", "StationIndex", "StationOnRoute"]

_DENSIFY_STEP_MILES = 0.5
"""Longest gap between route points used for matching, so a mile marker is off by 0.25 at most."""


@dataclass(frozen=True, slots=True)
class FuelStation:
    """A truck stop that sells diesel at a known retail price."""

    station_id: int
    name: str
    address: str
    city: str
    state: str
    price_per_gallon: Decimal
    location: Coordinate


@dataclass(frozen=True, slots=True)
class StationOnRoute:
    """A station near a route, placed at the route mile closest to it."""

    station: FuelStation
    mile_marker: float
    distance_from_route_miles: float


class StationIndex:
    """Immutable set of stations, built once, that finds those near a route."""

    def __init__(self, stations: Iterable[FuelStation]) -> None:
        """Store the stations and precompute their 3D positions."""
        self._stations = tuple(stations)
        latitudes = np.fromiter((s.location.latitude for s in self._stations), dtype=np.float64)
        longitudes = np.fromiter((s.location.longitude for s in self._stations), dtype=np.float64)
        self._points = _to_cartesian_miles(latitudes, longitudes)

    def __len__(self) -> int:
        """Return the number of stations in the index."""
        return len(self._stations)

    def along(self, route: Route, *, corridor_miles: float) -> list[StationOnRoute]:
        """Return the stations within ``corridor_miles`` of the route, ordered by mile marker.

        Mile markers are scaled so the last route point sits at ``route.distance_miles``,
        the distance the provider measured along the roads.
        """
        if not self._stations:
            return []
        latitudes, longitudes, miles = _densify(route)
        geometric_length = float(miles[-1])
        scale = route.distance_miles / geometric_length if geometric_length > 0 else 0.0
        tree = cKDTree(_to_cartesian_miles(latitudes, longitudes))
        # A chord this long subtends an arc of exactly corridor_miles on the sphere.
        chord = 2 * EARTH_RADIUS_MILES * math.sin(corridor_miles / (2 * EARTH_RADIUS_MILES))
        raw_distances, raw_nearest = tree.query(self._points, distance_upper_bound=chord)
        distances = np.asarray(raw_distances, dtype=np.float64)
        nearest = np.asarray(raw_nearest, dtype=np.int64)
        matched = np.flatnonzero(np.isfinite(distances))
        found = [
            StationOnRoute(
                station=self._stations[index],
                mile_marker=float(miles[nearest[index]]) * scale,
                distance_from_route_miles=float(distances[index]),
            )
            for index in matched.tolist()
        ]
        found.sort(key=lambda s: (s.mile_marker, s.station.station_id))
        return found


def _to_cartesian_miles(
    latitudes: NDArray[np.float64], longitudes: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Project degrees onto a sphere of Earth's radius so straight-line distance is in miles."""
    lat = np.radians(latitudes)
    lon = np.radians(longitudes)
    cos_lat = np.cos(lat)
    return (
        np.column_stack((cos_lat * np.cos(lon), cos_lat * np.sin(lon), np.sin(lat)))
        * EARTH_RADIUS_MILES
    )


def _densify(
    route: Route,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return latitudes, longitudes and cumulative miles with points at most 0.5 mile apart."""
    latitudes = np.fromiter((c.latitude for c in route.path), dtype=np.float64)
    longitudes = np.fromiter((c.longitude for c in route.path), dtype=np.float64)
    lengths = _haversine_array(latitudes[:-1], longitudes[:-1], latitudes[1:], longitudes[1:])
    pieces = np.maximum(1, np.ceil(lengths / _DENSIFY_STEP_MILES)).astype(np.int64)
    segment = np.repeat(np.arange(lengths.size), pieces)
    first_of_segment = np.repeat(np.cumsum(pieces) - pieces, pieces)
    fraction = (np.arange(segment.size) - first_of_segment) / np.repeat(pieces, pieces)
    segment_start_miles = np.concatenate(([0.0], np.cumsum(lengths)[:-1]))

    dense_latitudes = latitudes[segment] + (latitudes[segment + 1] - latitudes[segment]) * fraction
    dense_longitudes = (
        longitudes[segment] + (longitudes[segment + 1] - longitudes[segment]) * fraction
    )
    dense_miles = segment_start_miles[segment] + lengths[segment] * fraction
    total = float(lengths.sum())
    return (
        np.append(dense_latitudes, latitudes[-1]),
        np.append(dense_longitudes, longitudes[-1]),
        np.append(dense_miles, total),
    )


def _haversine_array(
    lat1: NDArray[np.float64],
    lon1: NDArray[np.float64],
    lat2: NDArray[np.float64],
    lon2: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Return element-wise great-circle distances in miles."""
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = phi2 - phi1
    dlambda = np.radians(lon2 - lon1)
    h = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return np.asarray(2 * EARTH_RADIUS_MILES * np.arcsin(np.minimum(1.0, np.sqrt(h))))
