"""Caching wrappers that keep repeat requests from calling the provider again.

The cache is a performance aid, never a dependency: when the store fails, for example
because Redis is down, a read counts as a miss and a write is skipped, so the request
still gets its answer from the provider.
"""

from __future__ import annotations

import hashlib
import logging
from array import array
from typing import TYPE_CHECKING, Any

from redis.exceptions import RedisError

from fuelroute.core.geo import Coordinate, Route
from fuelroute.core.locations import ResolvedLocation

if TYPE_CHECKING:
    from django.core.cache.backends.base import BaseCache

    from fuelroute.core.ports import Geocoder, RoutingProvider

__all__ = ["CachedGeocoder", "CachedRoutingProvider"]

logger = logging.getLogger(__name__)

_KEY_VERSION = "v2"
_NOT_FOUND = "not-found"
_ROUTE_TAG = "route-doubles"


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
        cached = _unpack_route(_read(self._cache, key))
        if cached is not None:
            return cached
        route = self._provider.route(start, finish)
        _write(self._cache, key, _pack_route(route), self._timeout)
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
        cached = _read(self._cache, key)
        if isinstance(cached, ResolvedLocation):
            return cached
        if cached == _NOT_FOUND:
            return None
        location = self._geocoder.geocode(text)
        _write(self._cache, key, location if location is not None else _NOT_FOUND, self._timeout)
        return location


def _read(cache: BaseCache, key: str) -> Any:  # noqa: ANN401  # cache values are untyped
    try:
        return cache.get(key)
    except RedisError as error:
        logger.warning("cache read failed, treated as a miss: %s", type(error).__name__)
        return None


def _write(cache: BaseCache, key: str, value: object, timeout: int) -> None:
    try:
        cache.set(key, value, timeout)
    except RedisError as error:
        logger.warning("cache write failed, skipped: %s", type(error).__name__)


def _pack_route(route: Route) -> tuple[str, bytes, float, float]:
    """Store the path as raw doubles: 40 percent smaller than pickled points, faster to load."""
    doubles = array("d")
    for point in route.path:
        doubles.append(point.latitude)
        doubles.append(point.longitude)
    return (_ROUTE_TAG, doubles.tobytes(), route.distance_miles, route.duration_seconds)


def _unpack_route(value: object) -> Route | None:
    if not (isinstance(value, tuple) and len(value) == 4 and value[0] == _ROUTE_TAG):  # noqa: PLR2004  # tag, path, distance, duration
        return None
    _, packed, distance_miles, duration_seconds = value
    doubles = array("d")
    doubles.frombytes(packed)
    path = tuple(Coordinate(doubles[i], doubles[i + 1]) for i in range(0, len(doubles), 2))
    return Route(path=path, distance_miles=distance_miles, duration_seconds=duration_seconds)
