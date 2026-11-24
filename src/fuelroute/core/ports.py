"""Interfaces the core needs from the outside world, implemented by adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from fuelroute.core.geo import Coordinate, Route
    from fuelroute.core.locations import ResolvedLocation

__all__ = ["Geocoder", "PlaceDirectory", "RoutingProvider"]


class RoutingProvider(Protocol):
    """Finds a driving route between two points."""

    def route(self, start: Coordinate, finish: Coordinate) -> Route:
        """Return the route, or raise a ``ProviderError`` or ``RouteNotFoundError``."""
        ...


class Geocoder(Protocol):
    """Turns free text such as a street address into a point in the USA."""

    def geocode(self, text: str) -> ResolvedLocation | None:
        """Return the best match, ``None`` when nothing matches, or raise ``ProviderError``."""
        ...


class PlaceDirectory(Protocol):
    """Looks up US cities and towns by name and state without any network call."""

    def find(self, name: str, state: str) -> ResolvedLocation | None:
        """Return the place, or ``None`` when the directory does not know it."""
        ...
