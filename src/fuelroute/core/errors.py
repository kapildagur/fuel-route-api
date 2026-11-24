"""Errors raised by the fuel route planner, all under one base class."""

from __future__ import annotations

__all__ = [
    "ConfigurationError",
    "DataFileError",
    "FuelRouteError",
    "InvalidLocationError",
    "InvalidRouteError",
    "InvalidStartFuelError",
    "LocationNotFoundError",
    "OutsideServiceAreaError",
    "ProviderAuthenticationError",
    "ProviderError",
    "ProviderRateLimitedError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RouteNotFoundError",
    "RouteTooLongError",
    "UnreachableSegmentError",
]


class FuelRouteError(Exception):
    """Base class for every error this package raises on purpose."""

    code: str = "fuel_route_error"


class InvalidLocationError(FuelRouteError, ValueError):
    """A location query is empty, too long or malformed."""

    code = "invalid_location"


class LocationNotFoundError(FuelRouteError):
    """No place or address matches a location query."""

    code = "location_not_found"

    def __init__(self, query: str) -> None:
        """Record the query that matched nothing."""
        super().__init__(f"No place in the USA matches {query!r}.")
        self.query = query


class OutsideServiceAreaError(FuelRouteError):
    """A location resolves to a point outside the USA."""

    code = "outside_service_area"

    def __init__(self, query: str, latitude: float, longitude: float) -> None:
        """Record the query and the point it resolved to."""
        super().__init__(
            f"{query!r} resolves to {latitude:.5f},{longitude:.5f}, which is outside the USA."
        )
        self.query = query


class InvalidStartFuelError(FuelRouteError, ValueError):
    """The starting fuel is negative or more than the tank holds."""

    code = "invalid_start_fuel"


class ConfigurationError(FuelRouteError, ValueError):
    """A setting such as tank size, fuel economy or corridor width is out of range."""

    code = "configuration_error"


class InvalidRouteError(FuelRouteError, ValueError):
    """A route has fewer than two points or a negative distance or duration."""

    code = "invalid_route"


class RouteNotFoundError(FuelRouteError):
    """The routing provider found no drivable route between the two points."""

    code = "route_not_found"


class RouteTooLongError(FuelRouteError):
    """The route is longer than the routing provider accepts."""

    code = "route_too_long"


class UnreachableSegmentError(FuelRouteError):
    """No fuel station on the route lies within the vehicle's range."""

    code = "unreachable_segment"

    def __init__(self, *, fuel_runs_out_at_mile: float, next_station_mile: float | None) -> None:
        """Record where the fuel runs out and where the next station is, if any."""
        if next_station_mile is None:
            detail = "and no station lies further along the route"
        else:
            detail = f"and the next station is at mile {next_station_mile:.1f}"
        super().__init__(
            f"The vehicle runs out of fuel at mile {fuel_runs_out_at_mile:.1f} {detail}."
        )
        self.fuel_runs_out_at_mile = fuel_runs_out_at_mile
        self.next_station_mile = next_station_mile


class ProviderError(FuelRouteError):
    """The routing or geocoding provider failed or returned something unusable."""

    code = "provider_error"


class ProviderUnavailableError(ProviderError):
    """The provider could not be reached or answered with a server error."""

    code = "provider_unavailable"


class ProviderTimeoutError(ProviderUnavailableError):
    """The provider did not answer within the configured timeout."""

    code = "provider_timeout"


class ProviderRateLimitedError(ProviderError):
    """The provider refused the call because a quota is used up."""

    code = "provider_rate_limited"

    def __init__(self, message: str, *, retry_after_seconds: int | None) -> None:
        """Record how long the provider asks callers to wait, when it says."""
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderAuthenticationError(ProviderError):
    """The provider rejected the configured API key."""

    code = "provider_authentication_failed"


class DataFileError(FuelRouteError):
    """A data file is missing, has the wrong columns or holds a bad value."""

    code = "data_file_error"
