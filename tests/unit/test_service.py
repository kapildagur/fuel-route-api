from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from fuelroute.core.errors import (
    ConfigurationError,
    InvalidLocationError,
    LocationNotFoundError,
    OutsideServiceAreaError,
)
from fuelroute.core.geo import Coordinate, Route
from fuelroute.core.locations import LocationSource, ResolvedLocation
from fuelroute.core.planner import Vehicle
from fuelroute.core.service import FuelPlanService
from fuelroute.core.stations import StationIndex
from tests.helpers import road_route, station


@dataclass
class FakeRouting:
    route_to_return: Route
    calls: list[tuple[Coordinate, Coordinate]] = field(default_factory=list)

    def route(self, start: Coordinate, finish: Coordinate) -> Route:
        self.calls.append((start, finish))
        return self.route_to_return


@dataclass
class FakeGeocoder:
    answers: dict[str, ResolvedLocation] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def geocode(self, text: str) -> ResolvedLocation | None:
        self.calls.append(text)
        return self.answers.get(text)


@dataclass
class FakePlaces:
    places: dict[tuple[str, str], ResolvedLocation] = field(default_factory=dict)

    def find(self, name: str, state: str) -> ResolvedLocation | None:
        return self.places.get((name, state))


def _located(label: str, coordinate: Coordinate, source: LocationSource) -> ResolvedLocation:
    return ResolvedLocation(label=label, coordinate=coordinate, source=source)


def _service(
    *,
    routing: FakeRouting | None = None,
    geocoder: FakeGeocoder | None = None,
    places: FakePlaces | None = None,
    stations: StationIndex | None = None,
) -> FuelPlanService:
    return FuelPlanService(
        routing=routing or FakeRouting(road_route(800)),
        geocoder=geocoder or FakeGeocoder(),
        places=places or FakePlaces(),
        stations=stations
        or StationIndex([station(1, mile=300, price="3.000"), station(2, mile=600, price="2.900")]),
        vehicle=Vehicle(),
        corridor_miles=5,
        min_stop_saving=Decimal(5),
    )


def test_coordinates_need_no_lookup() -> None:
    geocoder = FakeGeocoder()
    service = _service(geocoder=geocoder)
    location = service.resolve("40,-100")
    assert location.source is LocationSource.COORDINATES
    assert location.coordinate == Coordinate(40, -100)
    assert geocoder.calls == []


def test_known_town_comes_from_the_place_directory() -> None:
    town = _located("Hays, KS", Coordinate(38.88, -99.33), LocationSource.PLACE_DIRECTORY)
    geocoder = FakeGeocoder()
    service = _service(places=FakePlaces({("Hays", "KS"): town}), geocoder=geocoder)
    assert service.resolve("Hays, KS") == town
    assert geocoder.calls == []


def test_unknown_town_falls_back_to_the_geocoder() -> None:
    match = _located("Tinytown, KS, USA", Coordinate(38.5, -98.0), LocationSource.GEOCODER)
    geocoder = FakeGeocoder({"Tinytown, KS": match})
    service = _service(geocoder=geocoder)
    assert service.resolve("Tinytown, ks") == match
    assert geocoder.calls == ["Tinytown, KS"]


def test_street_address_goes_to_the_geocoder() -> None:
    match = _located("1 Main St", Coordinate(38.5, -98.0), LocationSource.GEOCODER)
    service = _service(geocoder=FakeGeocoder({"1 Main St, Hays KS": match}))
    assert service.resolve("1 Main St,  Hays KS") == match


def test_query_nothing_matches_is_not_found() -> None:
    with pytest.raises(LocationNotFoundError, match="Atlantis"):
        _service().resolve("Atlantis")


def test_match_outside_the_usa_is_rejected() -> None:
    paris = _located("Paris, France", Coordinate(48.86, 2.35), LocationSource.GEOCODER)
    service = _service(geocoder=FakeGeocoder({"Paris France": paris}))
    with pytest.raises(OutsideServiceAreaError, match="outside the USA"):
        service.resolve("Paris France")


def test_coordinates_outside_the_usa_are_rejected() -> None:
    with pytest.raises(OutsideServiceAreaError):
        _service().resolve("51.5,-0.12")


def test_blank_query_is_invalid() -> None:
    with pytest.raises(InvalidLocationError):
        _service().resolve("  ")


def test_plan_routes_once_and_drops_a_stop_that_saves_little() -> None:
    routing = FakeRouting(road_route(790))
    service = _service(routing=routing)
    plan = service.plan("40,-100", "40,-90")
    assert len(routing.calls) == 1
    assert plan.stations_considered == 2
    # Cheapest: about 10 gal at mile 300 ($3.00), then 19 gal at mile 600 ($2.90).
    # Skipping the second stop costs about $1.90 more, under the $5 default.
    assert plan.stop_plan.lowest_cost_stop_count == 2
    assert float(plan.stop_plan.lowest_cost) == pytest.approx(85.10, abs=0.10)
    assert [s.station_on_route.station.station_id for s in plan.stops] == [1]
    assert float(plan.gallons_purchased) == pytest.approx(29.0, abs=0.05)
    assert float(plan.total_cost) == pytest.approx(87.00, abs=0.15)
    assert plan.fuel_used_gallons == pytest.approx(79)
    assert plan.arrival_fuel_gallons == pytest.approx(0, abs=1e-6)
    assert plan.min_stop_saving == Decimal(5)


def test_plan_without_purchases_reports_the_fuel_left() -> None:
    service = _service(routing=FakeRouting(road_route(200)))
    plan = service.plan("40,-100", "40,-96", start_fuel_gallons=30)
    assert plan.stops == ()
    assert plan.total_cost == Decimal("0.00")
    assert plan.arrival_fuel_gallons == pytest.approx(10)


def test_request_values_override_the_service_defaults() -> None:
    service = _service()
    plan = service.plan("40,-100", "40,-96", start_fuel_gallons=40, min_stop_saving=Decimal(0))
    assert plan.start_fuel_gallons == 40
    assert plan.min_stop_saving == Decimal(0)
    assert [s.station_on_route.station.station_id for s in plan.stops] == [1, 2]


@pytest.mark.parametrize(
    ("corridor", "saving", "message"),
    [(0, Decimal(5), "Corridor width"), (5, Decimal(-1), "Minimum stop saving")],
)
def test_service_rejects_bad_settings(corridor: float, saving: Decimal, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        FuelPlanService(
            routing=FakeRouting(road_route(10)),
            geocoder=FakeGeocoder(),
            places=FakePlaces(),
            stations=StationIndex([]),
            vehicle=Vehicle(),
            corridor_miles=corridor,
            min_stop_saving=saving,
        )


def test_service_reports_its_station_count() -> None:
    assert _service().station_count == 2
