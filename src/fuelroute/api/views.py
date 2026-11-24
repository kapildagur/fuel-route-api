"""HTTP views: the fuel plan endpoint, the map page and the health check."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.views.generic import TemplateView
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from fuelroute.api.container import get_fuel_plan_service
from fuelroute.api.serializers import (
    FuelPlanQuerySerializer,
    FuelPlanSerializer,
    ProblemSerializer,
)

if TYPE_CHECKING:
    from rest_framework.request import Request

__all__ = ["FuelPlanView", "HealthView", "MapView"]


class FuelPlanView(APIView):
    """Plans the cheapest fuel stops between two US locations."""

    @extend_schema(
        operation_id="get_fuel_plan",
        summary="Plan the cheapest fuel stops for a route",
        parameters=[FuelPlanQuerySerializer],
        responses={
            200: FuelPlanSerializer,
            400: OpenApiResponse(ProblemSerializer, description="A parameter is invalid."),
            422: OpenApiResponse(
                ProblemSerializer,
                description="Location unknown or outside the USA, no route, or no fuel in range.",
            ),
            429: OpenApiResponse(ProblemSerializer, description="Too many requests."),
            502: OpenApiResponse(ProblemSerializer, description="The routing service failed."),
            503: OpenApiResponse(ProblemSerializer, description="Routing quota or key problem."),
            504: OpenApiResponse(ProblemSerializer, description="The routing service timed out."),
        },
    )
    def get(self, request: Request) -> Response:
        """Return the route, the fuel stops and the total cost."""
        query = FuelPlanQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values: dict[str, Any] = query.validated_data
        plan = get_fuel_plan_service().plan(
            values["start"],
            values["finish"],
            start_fuel_gallons=values.get("start_fuel_gallons"),
            min_stop_saving=values.get("min_stop_saving"),
        )
        context = {"request": request, "query": request.query_params}
        return Response(FuelPlanSerializer(plan, context=context).data)


class HealthView(APIView):
    """Reports whether the station data is loaded; never calls the routing provider."""

    throttle_classes = ()

    @extend_schema(operation_id="get_health", summary="Health check", responses={200: dict})
    def get(self, _request: Request) -> Response:
        """Return ``ok`` and the station count, or 503 when no station is loaded."""
        stations = get_fuel_plan_service().station_count
        if stations == 0:
            return Response({"status": "no_stations", "stations": 0}, status=503)
        return Response({"status": "ok", "stations": stations})


class MapView(TemplateView):
    """Shows the plan on a map; the page fetches the JSON endpoint itself."""

    template_name = "fuelroute/map.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401  # Django passes URL keyword arguments
        """Add the tank size, which bounds the start fuel field."""
        context = super().get_context_data(**kwargs)
        context["tank_gallons"] = settings.FUELROUTE_TANK_GALLONS
        return context
