"""The use case: resolve two locations, route between them and plan the fuel stops."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from fuelroute.core.errors import (
    ConfigurationError,
    LocationNotFoundError,
    OutsideServiceAreaError,
)
from fuelroute.core.locations import (
    CoordinateQuery,
    LocationSource,
    PlaceQuery,
    ResolvedLocation,
    is_in_united_states,
    parse_location_query,
)
from fuelroute.core.planner import Vehicle, plan_fuel_stops

if TYPE_CHECKING:
    from fuelroute.core.geo import Route
    from fuelroute.core.planner import FuelStop, StopPlan
    from fuelroute.core.ports import Geocoder, PlaceDirectory, RoutingProvider
    from fuelroute.core.stations import StationIndex

__all__ = ["FuelPlan", "FuelPlanService"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FuelPlan:
    """A route, the fuel stops chosen for it, and their totals."""

    start: ResolvedLocation
    finish: ResolvedLocation
    route: Route
    vehicle: Vehicle
    start_fuel_gallons: float
    min_stop_saving: Decimal
    stop_plan: StopPlan
    stations_considered: int

    @property
    def stops(self) -> tuple[FuelStop, ...]:
        """Return the stops in driving order."""
        return self.stop_plan.stops

    @property
    def gallons_purchased(self) -> Decimal:
        """Return the sum of the rounded gallons bought at every stop."""
        return sum((stop.gallons for stop in self.stops), Decimal("0.000"))

    @property
    def total_cost(self) -> Decimal:
        """Return the sum of the stop costs, so it matches the stops to the cent."""
        return self.stop_plan.total_cost

    @property
    def fuel_used_gallons(self) -> float:
        """Return the fuel the whole route burns."""
        return self.route.distance_miles / self.vehicle.miles_per_gallon

    @property
    def arrival_fuel_gallons(self) -> float:
        """Return the fuel left at the finish; zero whenever any fuel was bought."""
        bought = sum(stop.gallons_exact for stop in self.stops)
        return max(0.0, self.start_fuel_gallons + bought - self.fuel_used_gallons)


class FuelPlanService:
    """Plans the cheapest fuel stops between two US locations."""

    def __init__(  # noqa: PLR0913  # each collaborator is a separate port or setting
        self,
        *,
        routing: RoutingProvider,
        geocoder: Geocoder,
        places: PlaceDirectory,
        stations: StationIndex,
        vehicle: Vehicle,
        corridor_miles: float,
        min_stop_saving: Decimal,
    ) -> None:
        """Wire the service to its adapters and settings."""
        if corridor_miles <= 0:
            msg = f"Corridor width {corridor_miles!r} miles must be positive."
            raise ConfigurationError(msg)
        if min_stop_saving < 0:
            msg = f"Minimum stop saving {min_stop_saving!r} must not be negative."
            raise ConfigurationError(msg)
        self._routing = routing
        self._geocoder = geocoder
        self._places = places
        self._stations = stations
        self.vehicle = vehicle
        self.corridor_miles = corridor_miles
        self.min_stop_saving = min_stop_saving

    @property
    def station_count(self) -> int:
        """Return how many stations the index holds."""
        return len(self._stations)

    def plan(
        self,
        start: str,
        finish: str,
        *,
        start_fuel_gallons: float | None = None,
        min_stop_saving: Decimal | None = None,
    ) -> FuelPlan:
        """Return the fuel plan from ``start`` to ``finish``.

        ``start_fuel_gallons`` defaults to a full tank. ``min_stop_saving`` defaults to
        the service setting; zero gives the cheapest plan.

        Raises:
            InvalidLocationError: a query is blank, too long or out of range.
            LocationNotFoundError: a query matches no place.
            OutsideServiceAreaError: a query resolves outside the USA.
            InvalidStartFuelError: the starting fuel does not fit the tank.
            RouteNotFoundError: no road connects the two points.
            RouteTooLongError: the route exceeds the provider's length limit.
            UnreachableSegmentError: a stretch has no station within range.
            ProviderError: the routing or geocoding provider failed.
        """
        fuel = self.vehicle.tank_gallons if start_fuel_gallons is None else start_fuel_gallons
        saving = self.min_stop_saving if min_stop_saving is None else min_stop_saving
        started = time.perf_counter()
        start_location = self.resolve(start)
        finish_location = self.resolve(finish)
        route = self._routing.route(start_location.coordinate, finish_location.coordinate)
        nearby = self._stations.along(route, corridor_miles=self.corridor_miles)
        stop_plan = plan_fuel_stops(
            nearby,
            distance_miles=route.distance_miles,
            vehicle=self.vehicle,
            start_fuel_gallons=fuel,
            min_stop_saving=saving,
        )
        plan = FuelPlan(
            start=start_location,
            finish=finish_location,
            route=route,
            vehicle=self.vehicle,
            start_fuel_gallons=fuel,
            min_stop_saving=saving,
            stop_plan=stop_plan,
            stations_considered=len(nearby),
        )
        logger.info(
            "fuel plan ready: distance_miles=%.1f stations_considered=%d stops=%d "
            "total_cost=%s lowest_cost=%s elapsed_ms=%.1f",
            route.distance_miles,
            len(nearby),
            len(stop_plan.stops),
            stop_plan.total_cost,
            stop_plan.lowest_cost,
            (time.perf_counter() - started) * 1000,
        )
        return plan

    def resolve(self, text: str) -> ResolvedLocation:
        """Return the point a query names, using the geocoder only for free text.

        Raises:
            InvalidLocationError: the query is blank, too long or out of range.
            LocationNotFoundError: nothing matches the query.
            OutsideServiceAreaError: the match lies outside the USA.
        """
        query = parse_location_query(text)
        resolved: ResolvedLocation | None
        if isinstance(query, CoordinateQuery):
            resolved = ResolvedLocation(
                label=f"{query.coordinate.latitude},{query.coordinate.longitude}",
                coordinate=query.coordinate,
                source=LocationSource.COORDINATES,
            )
        elif isinstance(query, PlaceQuery):
            resolved = self._places.find(query.name, query.state)
            if resolved is None:
                resolved = self._geocoder.geocode(f"{query.name}, {query.state}")
        else:
            resolved = self._geocoder.geocode(query.text)

        if resolved is None:
            raise LocationNotFoundError(text)
        if not is_in_united_states(resolved.coordinate):
            raise OutsideServiceAreaError(
                text, resolved.coordinate.latitude, resolved.coordinate.longitude
            )
        return resolved
