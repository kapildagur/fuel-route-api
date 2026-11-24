"""Request validation and response shapes for the fuel plan endpoint."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from fuelroute.api.geojson import fuel_plan_feature_collection
from fuelroute.core.locations import MAX_QUERY_LENGTH
from fuelroute.core.service import FuelPlan  # noqa: TC001  # drf-spectacular reads method hints at runtime

__all__ = [
    "FuelPlanQuerySerializer",
    "FuelPlanSerializer",
    "ProblemSerializer",
]

_SECONDS_PER_HOUR = 3600


class RoundedFloatField(serializers.FloatField):
    """A float rounded for display; the planner keeps full precision."""

    def __init__(self, *, decimals: int, **kwargs: Any) -> None:  # noqa: ANN401  # forwards DRF field options
        """Round output to ``decimals`` places."""
        super().__init__(**kwargs)
        self.decimals = decimals

    def to_representation(self, value: Any) -> float:  # type: ignore[override]  # noqa: ANN401  # DRF stubs say str; JSON gets a number
        """Return the value rounded."""
        return round(float(value), self.decimals)


def _money(**kwargs: Any) -> serializers.DecimalField:  # noqa: ANN401  # forwards DRF field options
    return serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=False, rounding=ROUND_HALF_UP, **kwargs
    )


def _gallons(**kwargs: Any) -> serializers.DecimalField:  # noqa: ANN401  # forwards DRF field options
    return serializers.DecimalField(
        max_digits=12, decimal_places=3, coerce_to_string=False, rounding=ROUND_HALF_UP, **kwargs
    )


class FuelPlanQuerySerializer(serializers.Serializer[dict[str, Any]]):
    """Query parameters of ``GET /api/v1/fuel-plan``."""

    start = serializers.CharField(
        max_length=MAX_QUERY_LENGTH,
        help_text='Where the trip begins: "City, ST", "latitude,longitude" or a street address.',
    )
    finish = serializers.CharField(
        max_length=MAX_QUERY_LENGTH,
        help_text="Where the trip ends, in the same forms as start.",
    )
    start_fuel_gallons = serializers.FloatField(
        required=False,
        min_value=0,
        help_text="Fuel in the tank at the start. Defaults to a full tank.",
    )
    min_stop_saving = serializers.DecimalField(
        required=False,
        max_digits=6,
        decimal_places=2,
        min_value=Decimal(0),
        max_value=Decimal(1000),
        help_text=(
            "Drop a stop when skipping it costs less than this many dollars more. "
            "0 returns the cheapest plan. Defaults to the server setting, 5.00."
        ),
    )


class LocationSerializer(serializers.Serializer[Any]):
    """A resolved start or finish."""

    # Serializer fields shadow Field attributes only in the type stubs; DRF pops them at runtime.
    label = serializers.CharField()  # type: ignore[assignment]
    latitude = serializers.FloatField(source="coordinate.latitude")
    longitude = serializers.FloatField(source="coordinate.longitude")
    source = serializers.CharField(  # type: ignore[assignment]
        help_text="coordinates, place_directory (no provider call) or geocoder."
    )


class RouteSerializer(serializers.Serializer[Any]):
    """Distance and driving time of the route."""

    distance_miles = RoundedFloatField(decimals=1)
    duration_hours = serializers.SerializerMethodField()

    def get_duration_hours(self, route: Any) -> float:  # noqa: ANN401  # DRF passes the source object
        """Return the driving time in hours."""
        return round(float(route.duration_seconds) / _SECONDS_PER_HOUR, 2)


class VehicleSerializer(serializers.Serializer[Any]):
    """The vehicle the plan assumes."""

    tank_gallons = serializers.FloatField(source="vehicle.tank_gallons")
    miles_per_gallon = serializers.FloatField(source="vehicle.miles_per_gallon")
    range_miles = serializers.FloatField(source="vehicle.range_miles")
    start_fuel_gallons = RoundedFloatField(decimals=3)


class FuelStopSerializer(serializers.Serializer[Any]):
    """One purchase, in driving order."""

    station_id = serializers.IntegerField(source="station_on_route.station.station_id")
    name = serializers.CharField(source="station_on_route.station.name")
    address = serializers.CharField(source="station_on_route.station.address")
    city = serializers.CharField(source="station_on_route.station.city")
    state = serializers.CharField(source="station_on_route.station.state")
    latitude = serializers.FloatField(source="station_on_route.station.location.latitude")
    longitude = serializers.FloatField(source="station_on_route.station.location.longitude")
    mile_marker = RoundedFloatField(decimals=1, source="station_on_route.mile_marker")
    distance_from_route_miles = RoundedFloatField(
        decimals=1, source="station_on_route.distance_from_route_miles"
    )
    price_per_gallon = serializers.DecimalField(
        max_digits=12,
        decimal_places=8,
        coerce_to_string=False,
        normalize_output=True,
        source="station_on_route.station.price_per_gallon",
    )
    gallons = _gallons()
    cost = _money()


class LowestCostPlanSerializer(serializers.Serializer[Any]):
    """Size and cost of the cheapest plan, before stops that save little are dropped."""

    fuel_stop_count = serializers.IntegerField(source="lowest_cost_stop_count")
    total_fuel_cost = _money(source="lowest_cost")


class SummarySerializer(serializers.Serializer[Any]):
    """Totals of the plan."""

    fuel_stop_count = serializers.SerializerMethodField()
    gallons_purchased = _gallons()
    total_fuel_cost = _money(source="total_cost")
    currency = serializers.SerializerMethodField()
    min_stop_saving = _money()
    lowest_cost_plan = LowestCostPlanSerializer(source="stop_plan")
    fuel_used_gallons = RoundedFloatField(decimals=3)
    arrival_fuel_gallons = RoundedFloatField(decimals=3)
    stations_considered = serializers.IntegerField(
        help_text="Stations within the corridor around the route."
    )

    def get_fuel_stop_count(self, plan: FuelPlan) -> int:
        """Return the number of stops."""
        return len(plan.stops)

    def get_currency(self, _plan: FuelPlan) -> str:
        """Return the currency of every amount."""
        return "USD"


class FuelPlanSerializer(serializers.Serializer[Any]):
    """The response of ``GET /api/v1/fuel-plan``."""

    start = LocationSerializer()
    finish = LocationSerializer()
    route = RouteSerializer()
    vehicle = VehicleSerializer(source="*")
    fuel_stops = FuelStopSerializer(many=True, source="stops")
    summary = SummarySerializer(source="*")
    map = serializers.SerializerMethodField()
    map_url = serializers.SerializerMethodField()

    @extend_schema_field(OpenApiTypes.OBJECT)
    def get_map(self, plan: FuelPlan) -> dict[str, Any]:
        """Return the route and stops as a GeoJSON FeatureCollection."""
        return fuel_plan_feature_collection(
            plan, tolerance_meters=settings.FUELROUTE_MAP_TOLERANCE_METERS
        )

    def get_map_url(self, _plan: FuelPlan) -> str:
        """Return a link to the map page for the same query."""
        request = self.context["request"]
        query = urlencode(self.context["query"])
        return str(request.build_absolute_uri(f"{reverse('fuel-map')}?{query}"))


class ProblemSerializer(serializers.Serializer[Any]):
    """An error response in the RFC 9457 problem details format."""

    type = serializers.CharField()
    title = serializers.CharField()
    status = serializers.IntegerField()
    detail = serializers.CharField()
    code = serializers.CharField()
