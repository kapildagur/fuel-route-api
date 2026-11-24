"""OpenRouteService client for driving routes and address geocoding."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Final

import httpx

from fuelroute.core.errors import (
    InvalidRouteError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RouteNotFoundError,
    RouteTooLongError,
)
from fuelroute.core.geo import Coordinate, Route
from fuelroute.core.locations import LocationSource, ResolvedLocation

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DEFAULT_BASE_URL", "OpenRouteServiceClient"]

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL: Final = "https://api.openrouteservice.org"
_METERS_PER_MILE: Final = 1609.344
_RETRY_DELAY_SECONDS: Final = 0.25
_RETRYABLE_STATUS: Final = frozenset({502, 503, 504})
# ORS error codes: 2004 a limit such as the 6,000 km route length is exceeded,
# 2009 no route connects the points, 2010 no road near a point.
_ROUTE_TOO_LONG_CODES: Final = frozenset({2004})
_ROUTE_NOT_FOUND_CODES: Final = frozenset({2009, 2010})
_HTTP_TOO_MANY_REQUESTS: Final = 429
_HTTP_SERVER_ERROR: Final = 500
_HTTP_CLIENT_ERROR: Final = 400
_AUTH_STATUSES: Final = frozenset({401, 403})
# Both endpoints answer in GeoJSON and the directions endpoint returns 406 to a client
# that accepts only application/json; errors come back as plain JSON.
_ACCEPT: Final = "application/geo+json, application/json"


class OpenRouteServiceClient:
    """Calls the OpenRouteService directions and geocode endpoints.

    One instance is shared by all requests; ``httpx.Client`` is safe to share across
    threads and keeps connections open between calls.
    """

    def __init__(  # noqa: PLR0913  # each option is a separate deployment setting
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        profile: str = "driving-hgv",
        timeout_seconds: float = 10.0,
        max_attempts: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create the HTTP client; ``transport`` replaces the network in tests."""
        if not api_key:
            msg = "An OpenRouteService API key is required."
            raise ProviderAuthenticationError(msg)
        self.profile = profile
        self._max_attempts = max(1, max_attempts)
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": api_key, "Accept": _ACCEPT},
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 3.0)),
            transport=transport,
        )

    def close(self) -> None:
        """Close the pooled connections."""
        self._client.close()

    def route(self, start: Coordinate, finish: Coordinate) -> Route:
        """Return the driving route for the configured profile.

        Raises:
            RouteNotFoundError: no road reaches one of the points or connects them.
            RouteTooLongError: the route exceeds the provider's length limit.
            ProviderError: the provider failed, refused the key or hit a quota.
        """
        body = {
            "coordinates": [
                [start.longitude, start.latitude],
                [finish.longitude, finish.latitude],
            ],
            "instructions": False,
            "geometry_simplify": True,
        }
        payload = self._send("POST", f"/v2/directions/{self.profile}/geojson", json=body)
        return _parse_route(payload)

    def geocode(self, text: str) -> ResolvedLocation | None:
        """Return the best US match for free text, or ``None`` when there is none.

        Raises:
            ProviderError: the provider failed, refused the key or hit a quota.
        """
        params = {"text": text, "boundary.country": "USA", "size": "1"}
        payload = self._send("GET", "/geocode/search", params=params)
        return _parse_geocode(payload)

    def _send(self, method: str, path: str, **kwargs: Any) -> Mapping[str, Any]:  # noqa: ANN401  # forwards httpx request options
        attempt = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                response = self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as error:
                if attempt < self._max_attempts:
                    time.sleep(_RETRY_DELAY_SECONDS)
                    continue
                msg = "OpenRouteService did not answer in time."
                raise ProviderTimeoutError(msg) from error
            except httpx.TransportError as error:
                if attempt < self._max_attempts:
                    time.sleep(_RETRY_DELAY_SECONDS)
                    continue
                msg = f"OpenRouteService could not be reached: {type(error).__name__}."
                raise ProviderUnavailableError(msg) from error

            logger.info(
                "openrouteservice call: method=%s path=%s status=%d attempt=%d elapsed_ms=%.1f",
                method,
                path,
                response.status_code,
                attempt,
                (time.perf_counter() - started) * 1000,
            )
            if response.status_code in _RETRYABLE_STATUS and attempt < self._max_attempts:
                time.sleep(_RETRY_DELAY_SECONDS)
                continue
            return _payload_or_raise(response)


def _payload_or_raise(response: httpx.Response) -> Mapping[str, Any]:
    status = response.status_code
    payload = _json(response)
    if status < _HTTP_CLIENT_ERROR:
        if payload is None:
            msg = "OpenRouteService returned a body that is not a JSON object."
            raise ProviderError(msg)
        return payload

    code, message = _error_details(payload)
    if status in _AUTH_STATUSES:
        msg = f"OpenRouteService rejected the API key (HTTP {status})."
        raise ProviderAuthenticationError(msg)
    if status == _HTTP_TOO_MANY_REQUESTS:
        retry_after = response.headers.get("Retry-After", "")
        msg = "OpenRouteService quota is used up; try again later."
        raise ProviderRateLimitedError(
            msg, retry_after_seconds=int(retry_after) if retry_after.isdigit() else None
        )
    if code in _ROUTE_TOO_LONG_CODES:
        msg = f"The route is longer than OpenRouteService allows: {message}"
        raise RouteTooLongError(msg)
    if code in _ROUTE_NOT_FOUND_CODES:
        msg = f"No drivable route connects the two locations: {message}"
        raise RouteNotFoundError(msg)
    if status >= _HTTP_SERVER_ERROR:
        msg = f"OpenRouteService failed with HTTP {status}."
        raise ProviderUnavailableError(msg)
    msg = f"OpenRouteService refused the request (HTTP {status}, code {code}): {message}"
    raise ProviderError(msg)


def _json(response: httpx.Response) -> Mapping[str, Any] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _error_details(payload: Mapping[str, Any] | None) -> tuple[int | None, str]:
    error = (payload or {}).get("error")
    if isinstance(error, dict):
        code = error.get("code")
        return (code if isinstance(code, int) else None, str(error.get("message", "")))
    if isinstance(error, str):
        return None, error
    return None, ""


def _parse_route(payload: Mapping[str, Any]) -> Route:
    try:
        feature = payload["features"][0]
        coordinates = feature["geometry"]["coordinates"]
        summary = feature["properties"].get("summary", {})
        path = tuple(Coordinate(float(point[1]), float(point[0])) for point in coordinates)
        return Route(
            path=path,
            distance_miles=float(summary.get("distance", 0.0)) / _METERS_PER_MILE,
            duration_seconds=float(summary.get("duration", 0.0)),
        )
    except (KeyError, IndexError, TypeError, ValueError, InvalidRouteError) as error:
        msg = f"OpenRouteService returned a route this service cannot read: {error!r}."
        raise ProviderError(msg) from error


def _parse_geocode(payload: Mapping[str, Any]) -> ResolvedLocation | None:
    features = payload.get("features")
    if not isinstance(features, list) or not features:
        return None
    try:
        feature = features[0]
        longitude, latitude = feature["geometry"]["coordinates"][:2]
        label = str(feature.get("properties", {}).get("label") or "")
        coordinate = Coordinate(float(latitude), float(longitude))
    except (KeyError, IndexError, TypeError, ValueError) as error:
        msg = f"OpenRouteService returned a geocode result this service cannot read: {error!r}."
        raise ProviderError(msg) from error
    return ResolvedLocation(
        label=label or f"{coordinate.latitude},{coordinate.longitude}",
        coordinate=coordinate,
        source=LocationSource.GEOCODER,
    )
