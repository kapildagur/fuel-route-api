"""Caching wrappers that keep repeat requests from calling the provider again."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from fuelroute.core.geo import Route
from fuelroute.core.locations import ResolvedLocation

if TYPE_CHECKING:
    from django.core.cache.backends.base import BaseCache

    from fuelroute.core.geo import Coordinate
    from fuelroute.core.ports import Geocoder, RoutingProvider

__all__ = ["CachedGeocoder", "CachedRoutingProvider"]

_KEY_VERSION = "v1"
_NOT_FOUND = "not-found"


class CachedRoutingProvider:
    """Returns a cached route for the same two points, rounded to about a metre."""

    def __init__(
        self, provider: RoutingProvider, cache: BaseCache, *, namespace: str, timeout_seconds: int
    ) -> None:
        """Wrap ``provider``; ``namespace`` separates routing profiles."""
        self._provider = provider
        self._cache = cache
        self._namespace = namespace
        self._timeout = timeout_seconds

    def route(self, start: Coordinate, finish: Coordinate) -> Route:
        """Return the cached route or fetch and cache it."""
        key = (
            f"route:{_KEY_VERSION}:{self._namespace}:"
            f"{start.latitude:.5f},{start.longitude:.5f}:{finish.latitude:.5f},{finish.longitude:.5f}"
        )
        cached = self._cache.get(key)
        if isinstance(cached, Route):
            return cached
        route = self._provider.route(start, finish)
        self._cache.set(key, route, self._timeout)
        return route


class CachedGeocoder:
    """Returns cached geocoding answers, including "not found", for the same text."""

    def __init__(self, geocoder: Geocoder, cache: BaseCache, *, timeout_seconds: int) -> None:
        """Wrap ``geocoder``."""
        self._geocoder = geocoder
        self._cache = cache
        self._timeout = timeout_seconds

    def geocode(self, text: str) -> ResolvedLocation | None:
        """Return the cached answer or ask the geocoder and cache what it says."""
        # Hashing keeps keys short and free of characters some cache backends refuse.
        digest = hashlib.sha256(" ".join(text.casefold().split()).encode()).hexdigest()
        key = f"geocode:{_KEY_VERSION}:{digest}"
        cached = self._cache.get(key)
        if isinstance(cached, ResolvedLocation):
            return cached
        if cached == _NOT_FOUND:
            return None
        location = self._geocoder.geocode(text)
        self._cache.set(key, location if location is not None else _NOT_FOUND, self._timeout)
        return location
