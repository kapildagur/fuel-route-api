"""Turns every error into an RFC 9457 problem details response."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from fuelroute.core.errors import (
    FuelRouteError,
    InvalidLocationError,
    InvalidStartFuelError,
    LocationNotFoundError,
    OutsideServiceAreaError,
    ProviderAuthenticationError,
    ProviderError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RouteNotFoundError,
    RouteTooLongError,
    UnreachableSegmentError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["PROBLEM_CONTENT_TYPE", "problem_exception_handler"]

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"

# Most specific first: the first class an error is an instance of decides the answer.
_ERROR_RESPONSES: tuple[tuple[type[FuelRouteError], int, str], ...] = (
    (InvalidLocationError, status.HTTP_400_BAD_REQUEST, "Invalid location"),
    (InvalidStartFuelError, status.HTTP_400_BAD_REQUEST, "Invalid start fuel"),
    (LocationNotFoundError, status.HTTP_422_UNPROCESSABLE_ENTITY, "Location not found"),
    (OutsideServiceAreaError, status.HTTP_422_UNPROCESSABLE_ENTITY, "Location outside the USA"),
    (RouteNotFoundError, status.HTTP_422_UNPROCESSABLE_ENTITY, "No route found"),
    (RouteTooLongError, status.HTTP_422_UNPROCESSABLE_ENTITY, "Route too long"),
    (UnreachableSegmentError, status.HTTP_422_UNPROCESSABLE_ENTITY, "No fuel within range"),
    (ProviderRateLimitedError, status.HTTP_503_SERVICE_UNAVAILABLE, "Routing quota used up"),
    (
        ProviderAuthenticationError,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Routing service misconfigured",
    ),
    (ProviderTimeoutError, status.HTTP_504_GATEWAY_TIMEOUT, "Routing service timed out"),
    (ProviderUnavailableError, status.HTTP_502_BAD_GATEWAY, "Routing service unavailable"),
    (ProviderError, status.HTTP_502_BAD_GATEWAY, "Routing service error"),
)


def problem_exception_handler(exc: Exception, context: Mapping[str, Any]) -> Response:
    """Return a problem details response for any error raised in a view."""
    if isinstance(exc, FuelRouteError):
        return _domain_problem(exc)

    response = exception_handler(exc, dict(context))
    if response is None:
        logger.error("unhandled error in %s", type(context.get("view")).__name__, exc_info=exc)
        return _problem(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Internal error",
            "The server failed to handle the request; the error is logged.",
            "internal_error",
        )
    if isinstance(exc, exceptions.ValidationError):
        problem = _problem(
            response.status_code,
            "Invalid request",
            "One or more query parameters are invalid.",
            "invalid_request",
            errors=response.data,
        )
    else:
        detail = exc.detail if isinstance(exc, exceptions.APIException) else str(exc)
        code = exc.default_code if isinstance(exc, exceptions.APIException) else "error"
        problem = _problem(response.status_code, response.status_text, str(detail), str(code))
    for header in ("Retry-After", "Allow", "WWW-Authenticate"):
        if header in response:
            problem[header] = response[header]
    return problem


def _domain_problem(exc: FuelRouteError) -> Response:
    http_status, title = next(
        ((code, title) for kind, code, title in _ERROR_RESPONSES if isinstance(exc, kind)),
        (status.HTTP_500_INTERNAL_SERVER_ERROR, "Internal error"),
    )
    extra: dict[str, Any] = {}
    if isinstance(exc, UnreachableSegmentError):
        extra["fuel_runs_out_at_mile"] = round(exc.fuel_runs_out_at_mile, 1)
        extra["next_station_mile"] = (
            None if exc.next_station_mile is None else round(exc.next_station_mile, 1)
        )

    if http_status >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("request failed: code=%s detail=%s", exc.code, exc)
    else:
        logger.info("request rejected: code=%s", exc.code)

    detail = str(exc)
    if isinstance(exc, ProviderAuthenticationError):
        # The operator needs the provider's reason; the caller only needs to know it is not them.
        detail = "The routing service is not configured correctly; the error is logged."
    response = _problem(http_status, title, detail, exc.code, **extra)
    if isinstance(exc, ProviderRateLimitedError) and exc.retry_after_seconds is not None:
        response["Retry-After"] = str(exc.retry_after_seconds)
    return response


def _problem(
    http_status: int,
    title: str,
    detail: str,
    code: str,
    **extra: Any,  # noqa: ANN401  # problem details allow extension members of any type
) -> Response:
    body = {
        "type": "about:blank",
        "title": title,
        "status": http_status,
        "detail": detail,
        "code": code,
        **extra,
    }
    return Response(body, status=http_status, content_type=PROBLEM_CONTENT_TYPE)
