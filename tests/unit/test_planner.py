from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fuelroute.core.errors import (
    ConfigurationError,
    InvalidStartFuelError,
    UnreachableSegmentError,
)
from fuelroute.core.planner import FuelStop, Vehicle, plan_fuel_stops
from tests.helpers import assert_feasible, exact_cost, on_route

if TYPE_CHECKING:
    from fuelroute.core.stations import StationOnRoute

VEHICLE = Vehicle(tank_gallons=50, miles_per_gallon=10)


def _plan(
    stations: list[StationOnRoute], distance: float, *, fuel: float = 50.0, saving: str = "0"
) -> tuple[FuelStop, ...]:
    return plan_fuel_stops(
        stations,
        distance_miles=distance,
        vehicle=VEHICLE,
        start_fuel_gallons=fuel,
        min_stop_saving=Decimal(saving),
    ).stops


def _purchases(stops: tuple[FuelStop, ...]) -> list[tuple[int, float]]:
    return [(s.station_on_route.station.station_id, round(s.gallons_exact, 6)) for s in stops]


# ---------------------------------------------------------------- vehicle


def test_vehicle_range_is_tank_times_economy() -> None:
    assert Vehicle(tank_gallons=50, miles_per_gallon=10).range_miles == 500


@pytest.mark.parametrize(("tank", "mpg"), [(0, 10), (50, 0), (-1, 10), (50, -5)])
def test_vehicle_without_positive_tank_and_economy_is_rejected(tank: float, mpg: float) -> None:
    with pytest.raises(ConfigurationError, match="must both be positive"):
        Vehicle(tank_gallons=tank, miles_per_gallon=mpg)


# ---------------------------------------------------------------- simple cases


def test_trip_within_starting_range_needs_no_stop() -> None:
    stations = [on_route(1, 100, "2.00")]
    assert _plan(stations, 500) == ()


def test_trip_without_stations_within_starting_range_needs_no_stop() -> None:
    assert _plan([], 300) == ()


def test_one_stop_buys_just_enough_to_finish() -> None:
    stations = [on_route(1, 300, "3.00")]
    assert _purchases(_plan(stations, 600)) == [(1, 10.0)]


def test_cheaper_station_ahead_gets_the_fuel() -> None:
    stations = [on_route(1, 100, "3.50"), on_route(2, 400, "3.00")]
    # Start full (500 mi), reach mile 400 with 10 gal, buy 30 more to cover the last 400 mi.
    assert _purchases(_plan(stations, 800)) == [(2, 30.0)]


def test_cheap_station_fills_the_tank_before_an_expensive_stretch() -> None:
    stations = [on_route(1, 100, "2.50"), on_route(2, 450, "4.00")]
    # At mile 100 (40 gal left) fill to 50, reach 450 with 15 gal, buy 20 more there.
    stops = _plan(stations, 800)
    assert _purchases(stops) == [(1, 10.0), (2, 20.0)]


def test_buys_only_enough_to_reach_the_next_cheaper_station() -> None:
    stations = [on_route(1, 450, "3.20"), on_route(2, 700, "2.90")]
    # Arrive at 450 with 5 gal; need 25 gal to reach 700; buy 20; then 30 gal to the finish.
    stops = _plan(stations, 1000)
    assert _purchases(stops) == [(1, 20.0), (2, 30.0)]


def test_stations_behind_the_start_or_past_the_finish_are_ignored() -> None:
    stations = [on_route(1, -5, "1.00"), on_route(2, 300, "3.00"), on_route(3, 700, "1.00")]
    assert _purchases(_plan(stations, 600)) == [(2, 10.0)]


def test_equal_prices_prefer_the_farther_station() -> None:
    stations = [on_route(1, 0, "3.00"), on_route(2, 200, "3.00"), on_route(3, 400, "3.00")]
    stops = _plan(stations, 900, fuel=0.0)
    assert [s.station_on_route.station.station_id for s in stops] == [1, 3]
    assert exact_cost(stops) == pytest.approx(270.0)


def test_station_at_mile_zero_serves_an_empty_tank() -> None:
    stations = [on_route(1, 0, "3.00")]
    assert _purchases(_plan(stations, 200, fuel=0.0)) == [(1, 20.0)]


def test_purchase_rounds_to_a_thousandth_of_a_gallon_and_a_cent() -> None:
    stations = [on_route(1, 0, "3.00733333")]
    (stop,) = _plan(stations, 123.4567, fuel=0.0)
    assert stop.gallons == Decimal("12.346")
    assert stop.cost == Decimal("37.13")


# ---------------------------------------------------------------- errors


@pytest.mark.parametrize("fuel", [-0.1, 50.01])
def test_start_fuel_outside_the_tank_is_rejected(fuel: float) -> None:
    with pytest.raises(InvalidStartFuelError, match="between 0 and the tank size"):
        _plan([], 100, fuel=fuel)


def test_negative_stop_saving_is_rejected() -> None:
    with pytest.raises(ConfigurationError, match="must not be negative"):
        _plan([], 100, saving="-1")


def test_gap_after_the_last_station_is_reported() -> None:
    stations = [on_route(1, 100, "3.00")]
    with pytest.raises(UnreachableSegmentError) as caught:
        _plan(stations, 700)
    assert caught.value.fuel_runs_out_at_mile == pytest.approx(600)
    assert caught.value.next_station_mile is None


def test_gap_between_stations_names_the_next_station() -> None:
    stations = [on_route(1, 100, "3.00"), on_route(2, 700, "3.00")]
    with pytest.raises(UnreachableSegmentError, match=r"next station is at mile 700\.0") as caught:
        _plan(stations, 900)
    assert caught.value.fuel_runs_out_at_mile == pytest.approx(600)


def test_empty_tank_with_no_station_at_the_start_is_unreachable() -> None:
    stations = [on_route(1, 3, "3.00")]
    with pytest.raises(UnreachableSegmentError) as caught:
        _plan(stations, 100, fuel=0.0)
    assert caught.value.fuel_runs_out_at_mile == 0
    assert caught.value.next_station_mile == 3


def test_no_station_at_all_on_a_long_route_is_unreachable() -> None:
    with pytest.raises(UnreachableSegmentError, match="no station lies further"):
        _plan([], 900)


# ---------------------------------------------------------------- fewer stops


def test_stop_saving_a_few_cents_is_dropped() -> None:
    # 45 gal reach mile 450 empty. The cheapest plan buys 1 gal there to reach the
    # station a cent cheaper at mile 460; skipping that second stop costs $0.44 more.
    stations = [on_route(1, 450, "3.000"), on_route(2, 460, "2.990")]
    cheapest = _plan(stations, 900, fuel=45.0, saving="0")
    assert _purchases(cheapest) == [(1, 1.0), (2, 44.0)]
    pruned = plan_fuel_stops(
        stations,
        distance_miles=900,
        vehicle=VEHICLE,
        start_fuel_gallons=45,
        min_stop_saving=Decimal(5),
    )
    assert _purchases(pruned.stops) == [(1, 45.0)]
    assert pruned.lowest_cost_stop_count == 2
    assert pruned.lowest_cost == Decimal("134.56")
    assert pruned.total_cost == Decimal("135.00")


def test_stop_saving_more_than_the_threshold_is_kept() -> None:
    # Skipping the $3.00 station means buying 45 gal at $4.00: $44 more.
    stations = [on_route(1, 450, "4.000"), on_route(2, 460, "3.000")]
    stops = _plan(stations, 900, fuel=45.0, saving="5")
    assert _purchases(stops) == [(1, 1.0), (2, 44.0)]


def test_stop_that_cannot_be_skipped_is_kept() -> None:
    stations = [on_route(1, 400, "3.000"), on_route(2, 800, "2.999")]
    stops = _plan(stations, 1200, saving="100")
    assert [s.station_on_route.station.station_id for s in stops] == [1, 2]


# ---------------------------------------------------------------- properties

MPG_ONE = 1.0


@st.composite
def integer_trips(draw: st.DrawFn) -> tuple[list[StationOnRoute], int, int, float]:
    """Trips where every distance and purchase is a whole gallon, so a DP is exact."""
    tank = draw(st.integers(min_value=1, max_value=12))
    distance = draw(st.integers(min_value=1, max_value=60))
    positions = draw(st.lists(st.integers(min_value=0, max_value=distance - 1), max_size=14))
    prices = draw(
        st.lists(
            st.integers(min_value=100, max_value=140),
            min_size=len(positions),
            max_size=len(positions),
        )
    )
    start = draw(st.integers(min_value=0, max_value=tank))
    stations = [
        on_route(index + 1, position, f"{price / 100:.2f}")
        for index, (position, price) in enumerate(zip(positions, prices, strict=True))
    ]
    return stations, distance, tank, float(start)


def _dp_lowest_cost(
    stations: list[StationOnRoute], distance: int, tank: int, start: float
) -> float | None:
    """Return the exact lowest cost by dynamic programming over whole-gallon fuel levels."""
    ordered = sorted(stations, key=lambda s: s.mile_marker)
    stops = [(int(s.mile_marker), float(s.station.price_per_gallon)) for s in ordered]
    best: dict[int, float] = {int(start): 0.0}
    position = 0
    for mile, price in [*stops, (distance, 0.0)]:
        leg = mile - position
        arrived = {fuel - leg: cost for fuel, cost in best.items() if fuel >= leg}
        if not arrived:
            return None
        if mile == distance:
            return min(arrived.values())
        best = {}
        for fuel, cost in arrived.items():
            for bought in range(tank - fuel + 1):
                level = fuel + bought
                total = cost + bought * price
                if total < best.get(level, float("inf")):
                    best[level] = total
        position = mile
    return None  # pragma: no cover  # the finish always ends the loop


@settings(max_examples=400, deadline=None)
@given(integer_trips())
def test_greedy_cost_equals_the_exact_optimum(
    trip: tuple[list[StationOnRoute], int, int, float],
) -> None:
    stations, distance, tank, start = trip
    vehicle = Vehicle(tank_gallons=tank, miles_per_gallon=MPG_ONE)
    optimum = _dp_lowest_cost(stations, distance, tank, start)
    if optimum is None:
        with pytest.raises(UnreachableSegmentError):
            plan_fuel_stops(
                stations, distance_miles=distance, vehicle=vehicle, start_fuel_gallons=start
            )
        return
    plan = plan_fuel_stops(
        stations, distance_miles=distance, vehicle=vehicle, start_fuel_gallons=start
    )
    assert exact_cost(plan.stops) == pytest.approx(optimum, abs=1e-6)
    assert_feasible(plan.stops, distance_miles=distance, vehicle=vehicle, start_fuel_gallons=start)


@settings(max_examples=300, deadline=None)
@given(integer_trips(), st.integers(min_value=1, max_value=20))
def test_dropping_stops_keeps_the_plan_feasible_and_bounded(
    trip: tuple[list[StationOnRoute], int, int, float], saving: int
) -> None:
    stations, distance, tank, start = trip
    vehicle = Vehicle(tank_gallons=tank, miles_per_gallon=MPG_ONE)
    try:
        plan = plan_fuel_stops(
            stations,
            distance_miles=distance,
            vehicle=vehicle,
            start_fuel_gallons=start,
            min_stop_saving=Decimal(saving) / 100,
        )
    except UnreachableSegmentError:
        return
    assert_feasible(plan.stops, distance_miles=distance, vehicle=vehicle, start_fuel_gallons=start)
    dropped = plan.lowest_cost_stop_count - len(plan.stops)
    assert dropped >= 0
    assert plan.total_cost >= plan.lowest_cost
    assert plan.total_cost - plan.lowest_cost <= Decimal(saving) / 100 * dropped
