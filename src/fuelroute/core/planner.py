"""Refuelling plan for a vehicle on a fixed route.

Planning runs in two passes.

1. The cheapest plan. The route is fixed, so the stations form a line. On a line the
   greedy rule from Khuller, Malekian and Mestre, "To fill or not to fill: The gas
   station problem" (ACM Transactions on Algorithms, 2011), gives the lowest cost:

   * If a cheaper station lies within a full tank's range, buy exactly enough fuel to
     reach the first such station.
   * Otherwise fill the tank and drive to the cheapest station within range.

2. Fewer stops. The cheapest plan can stop for a gallon to save a few cents. Each
   stop is tried without its station, smallest purchase first; the plan without it
   is kept when it has fewer stops and costs less than ``min_stop_saving`` more per
   stop removed. This pass is a heuristic: it never raises the cost by more than the
   saving threshold per dropped stop, but it does not promise the fewest stops.

The vehicle arrives at the finish with an empty tank, because fuel left over is fuel
paid for and not used.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from fuelroute.core.errors import (
    ConfigurationError,
    InvalidStartFuelError,
    UnreachableSegmentError,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from fuelroute.core.stations import StationOnRoute

__all__ = ["FuelStop", "StopPlan", "Vehicle", "plan_fuel_stops"]

_MILE_TOLERANCE = 1e-6
"""Distances closer than this count as equal, so float rounding never strands the vehicle."""

_GALLON_TOLERANCE = 1e-9
"""Purchases smaller than this are float noise, not stops."""

_GALLON_PRECISION = Decimal("0.001")
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class Vehicle:
    """Tank size and fuel economy, which together give the range."""

    tank_gallons: float = 50.0
    miles_per_gallon: float = 10.0

    def __post_init__(self) -> None:
        """Reject a tank or an economy that is not positive."""
        if self.tank_gallons <= 0 or self.miles_per_gallon <= 0:
            msg = (
                f"Tank size {self.tank_gallons!r} and fuel economy "
                f"{self.miles_per_gallon!r} must both be positive."
            )
            raise ConfigurationError(msg)

    @property
    def range_miles(self) -> float:
        """Return how far a full tank goes."""
        return self.tank_gallons * self.miles_per_gallon


@dataclass(frozen=True, slots=True)
class FuelStop:
    """A purchase at one station on the route."""

    station_on_route: StationOnRoute
    gallons_exact: float

    @property
    def gallons(self) -> Decimal:
        """Return the gallons bought, rounded to a thousandth."""
        return Decimal(repr(self.gallons_exact)).quantize(_GALLON_PRECISION, ROUND_HALF_UP)

    @property
    def cost(self) -> Decimal:
        """Return the price of the rounded gallons, rounded to the cent."""
        price = self.station_on_route.station.price_per_gallon
        return (self.gallons * price).quantize(_CENT, ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class StopPlan:
    """The stops to make, and the cost and size of the cheapest plan for comparison."""

    stops: tuple[FuelStop, ...]
    lowest_cost: Decimal
    lowest_cost_stop_count: int

    @property
    def total_cost(self) -> Decimal:
        """Return the sum of the stop costs, so it matches the stops to the cent."""
        return _total_cost(self.stops)


def plan_fuel_stops(
    stations: Sequence[StationOnRoute],
    *,
    distance_miles: float,
    vehicle: Vehicle,
    start_fuel_gallons: float,
    min_stop_saving: Decimal = _ZERO,
) -> StopPlan:
    """Return the stops that reach the finish, cheapest first, then with fewer stops.

    With ``min_stop_saving`` at zero the result is the cheapest plan.

    Raises:
        InvalidStartFuelError: ``start_fuel_gallons`` is negative or above the tank size.
        UnreachableSegmentError: a stretch of the route is longer than the fuel allows.
    """
    if not 0 <= start_fuel_gallons <= vehicle.tank_gallons:
        msg = (
            f"Start fuel {start_fuel_gallons!r} gallons must be between 0 and the "
            f"tank size of {vehicle.tank_gallons!r} gallons."
        )
        raise InvalidStartFuelError(msg)
    if min_stop_saving < 0:
        msg = f"Minimum stop saving {min_stop_saving!r} must not be negative."
        raise ConfigurationError(msg)

    candidates = sorted(
        (s for s in stations if 0 <= s.mile_marker < distance_miles),
        key=lambda s: (s.mile_marker, s.station.price_per_gallon, s.station.station_id),
    )
    trip = _Trip(distance_miles, vehicle, start_fuel_gallons)
    cheapest = _cheapest(candidates, trip)
    stops = cheapest
    if min_stop_saving > 0 and len(cheapest) > 1:
        stops = _drop_small_savings(candidates, cheapest, trip, min_stop_saving)
    return StopPlan(
        stops=stops,
        lowest_cost=_total_cost(cheapest),
        lowest_cost_stop_count=len(cheapest),
    )


@dataclass(frozen=True, slots=True)
class _Trip:
    distance_miles: float
    vehicle: Vehicle
    start_fuel_gallons: float


def _cheapest(candidates: Sequence[StationOnRoute], trip: _Trip) -> tuple[FuelStop, ...]:
    """Return the cheapest stops among ``candidates``, which are sorted by mile marker."""
    vehicle = trip.vehicle
    start_reach = trip.start_fuel_gallons * vehicle.miles_per_gallon
    if trip.distance_miles <= start_reach + _MILE_TOLERANCE:
        return ()
    if not candidates or candidates[0].mile_marker > start_reach + _MILE_TOLERANCE:
        raise UnreachableSegmentError(
            fuel_runs_out_at_mile=start_reach,
            next_station_mile=candidates[0].mile_marker if candidates else None,
        )
    first_leg = candidates[0].mile_marker / vehicle.miles_per_gallon
    return _greedy(
        candidates,
        distance_miles=trip.distance_miles,
        vehicle=vehicle,
        fuel=max(0.0, trip.start_fuel_gallons - first_leg),
    )


def _greedy(
    candidates: Sequence[StationOnRoute],
    *,
    distance_miles: float,
    vehicle: Vehicle,
    fuel: float,
) -> tuple[FuelStop, ...]:
    """Walk the stations from the first one, which the vehicle has already reached."""
    miles = [s.mile_marker for s in candidates]
    # Floats order these prices exactly (at most 8 decimals, under $100) and compare
    # several times faster than Decimal; money is still summed in Decimal.
    prices = [float(s.station.price_per_gallon) for s in candidates]
    next_cheaper = _next_cheaper(prices)
    stops: list[FuelStop] = []
    here = 0
    while True:
        reach = miles[here] + vehicle.range_miles
        cheaper = next_cheaper[here]
        target_mile = distance_miles if cheaper is None else miles[cheaper]
        if target_mile <= reach + _MILE_TOLERANCE:
            needed = (target_mile - miles[here]) / vehicle.miles_per_gallon
            bought = max(0.0, needed - fuel)
            if bought > _GALLON_TOLERANCE:
                stops.append(FuelStop(candidates[here], bought))
            if cheaper is None:
                return tuple(stops)
            fuel = max(0.0, fuel + bought - needed)
            here = cheaper
            continue

        following = _cheapest_within(miles, prices, after=here, limit=reach)
        if following is None:
            raise UnreachableSegmentError(
                fuel_runs_out_at_mile=reach,
                next_station_mile=miles[here + 1] if here + 1 < len(miles) else None,
            )
        if vehicle.tank_gallons - fuel > _GALLON_TOLERANCE:
            stops.append(FuelStop(candidates[here], vehicle.tank_gallons - fuel))
        fuel = vehicle.tank_gallons - (miles[following] - miles[here]) / vehicle.miles_per_gallon
        here = following


def _drop_small_savings(
    candidates: Sequence[StationOnRoute],
    cheapest: tuple[FuelStop, ...],
    trip: _Trip,
    min_stop_saving: Decimal,
) -> tuple[FuelStop, ...]:
    """Remove stops whose stations save less than ``min_stop_saving`` each."""
    # Positions by object identity: hashing the nested dataclasses on every trial is slow.
    position = {id(candidate): index for index, candidate in enumerate(candidates)}
    excluded: frozenset[int] = frozenset()
    current = cheapest
    while len(current) > 1:
        for stop in sorted(current, key=lambda s: s.gallons_exact):
            trial = excluded | {position[id(stop.station_on_route)]}
            remaining = [c for index, c in enumerate(candidates) if index not in trial]
            try:
                alternative = _cheapest(remaining, trip)
            except UnreachableSegmentError:
                continue
            dropped = len(current) - len(alternative)
            extra_cost = _total_cost(alternative) - _total_cost(current)
            if dropped > 0 and extra_cost < min_stop_saving * dropped:
                excluded = trial
                current = alternative
                break
        else:
            return current
    return current


def _total_cost(stops: Sequence[FuelStop]) -> Decimal:
    return sum((stop.cost for stop in stops), _ZERO)


def _next_cheaper(prices: Sequence[float]) -> list[int | None]:
    """Return, for each station, the index of the first later station that is cheaper."""
    result: list[int | None] = [None] * len(prices)
    stack: list[int] = []
    for index in range(len(prices) - 1, -1, -1):
        while stack and prices[stack[-1]] >= prices[index]:
            stack.pop()
        result[index] = stack[-1] if stack else None
        stack.append(index)
    return result


def _cheapest_within(
    miles: Sequence[float], prices: Sequence[float], *, after: int, limit: float
) -> int | None:
    """Return the cheapest station after ``after`` up to mile ``limit``; ties go to the farthest."""
    best: int | None = None
    index = after + 1
    while index < len(miles) and miles[index] <= limit + _MILE_TOLERANCE:
        if best is None or prices[index] <= prices[best]:
            best = index
        index += 1
    return best
