"""Database access for stations and places, returning core objects."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db import transaction

from fuelroute.core.errors import DataFileError
from fuelroute.core.geo import Coordinate
from fuelroute.core.locations import LocationSource, ResolvedLocation
from fuelroute.core.places import place_key
from fuelroute.core.stations import FuelStation, StationIndex
from fuelroute.data.fuel_prices import read_fuel_prices, select_us_stations
from fuelroute.data.gazetteer import read_places
from fuelroute.stations.models import FuelStationModel, PlaceModel

if TYPE_CHECKING:
    from pathlib import Path

    from fuelroute.data.gazetteer import PlaceRecord

__all__ = ["DatabasePlaceDirectory", "ImportReport", "import_station_data", "load_station_index"]

logger = logging.getLogger(__name__)

_STATION_FIELDS = (
    "station_id",
    "name",
    "address",
    "city",
    "state",
    "price_per_gallon",
    "latitude",
    "longitude",
)
"""The columns the index needs; rack and location source stay in the table."""


@dataclass(frozen=True, slots=True)
class ImportReport:
    """Counts from one import, and the stations left out because their town is unknown."""

    rows_read: int
    non_us_rows: int
    duplicate_rows: int
    places_imported: int
    stations_imported: int
    unlocated: tuple[tuple[int, str, str], ...]


class DatabasePlaceDirectory:
    """Finds US towns in the place table with one indexed query and no network call."""

    def find(self, name: str, state: str) -> ResolvedLocation | None:
        """Return the town, or ``None`` when the table does not hold it."""
        # (state, search_key) is unique and indexed, so the lookup needs no ORDER BY.
        rows = PlaceModel.objects.filter(
            state=state.upper(), search_key=place_key(name)
        ).values_list("name", "state", "latitude", "longitude")[:1]
        for place_name, place_state, latitude, longitude in rows:
            return ResolvedLocation(
                label=f"{place_name}, {place_state}",
                coordinate=Coordinate(latitude, longitude),
                source=LocationSource.PLACE_DIRECTORY,
            )
        return None


def load_station_index() -> StationIndex:
    """Read every station from the database into an immutable index."""
    stations = [
        FuelStation(
            station_id=row.station_id,
            name=row.name,
            address=row.address,
            city=row.city,
            state=row.state,
            price_per_gallon=row.price_per_gallon,
            location=Coordinate(row.latitude, row.longitude),
        )
        for row in FuelStationModel.objects.only(*_STATION_FIELDS)
        .order_by("station_id")
        .iterator(chunk_size=2000)
    ]
    return StationIndex(stations)


def import_station_data(*, prices_path: Path, places_path: Path) -> ImportReport:
    """Replace the place and station tables with the contents of the two files.

    The replacement runs in one transaction, so a failure leaves the old data in place.

    Raises:
        DataFileError: a file cannot be read, is malformed, or lists a place twice.
    """
    places = _unique_places(read_places(places_path), places_path)
    selection = select_us_stations(read_fuel_prices(prices_path))
    stations: list[FuelStationModel] = []
    unlocated: list[tuple[int, str, str]] = []
    for record in selection.records:
        place = places.get((place_key(record.city), record.state))
        if place is None:
            unlocated.append((record.station_id, record.city, record.state))
            continue
        stations.append(
            FuelStationModel(
                station_id=record.station_id,
                name=record.name,
                address=record.address,
                city=record.city,
                state=record.state,
                rack_id=record.rack_id,
                price_per_gallon=record.price_per_gallon,
                latitude=place.latitude,
                longitude=place.longitude,
                location_source=place.source.value,
            )
        )

    with transaction.atomic():
        FuelStationModel.objects.all().delete()
        PlaceModel.objects.all().delete()
        PlaceModel.objects.bulk_create(
            (
                PlaceModel(
                    name=place.name,
                    state=place.state,
                    search_key=key[0],
                    latitude=place.latitude,
                    longitude=place.longitude,
                    source=place.source.value,
                )
                for key, place in places.items()
            ),
            batch_size=2000,
        )
        FuelStationModel.objects.bulk_create(stations, batch_size=2000)

    for station_id, city, state in unlocated:
        logger.warning("station %d left out: no place for %s, %s", station_id, city, state)
    return ImportReport(
        rows_read=selection.rows_read,
        non_us_rows=selection.non_us_rows,
        duplicate_rows=selection.duplicate_rows,
        places_imported=len(places),
        stations_imported=len(stations),
        unlocated=tuple(unlocated),
    )


def _unique_places(places: list[PlaceRecord], path: Path) -> dict[tuple[str, str], PlaceRecord]:
    table: dict[tuple[str, str], PlaceRecord] = {}
    for place in places:
        if place.key in table:
            msg = f"{path}: {place.name}, {place.state} is listed twice under one name."
            raise DataFileError(msg)
        table[place.key] = place
    return table
