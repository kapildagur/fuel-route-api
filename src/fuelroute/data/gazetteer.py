"""Building and reading the place list that gives towns and station cities coordinates.

The list combines public sources, tried in this order for each station city:

1. ``data/place-aliases.csv``, hand-checked coordinates for names no source matches.
2. US Census Bureau Gazetteer, places (cities, towns and census-designated places).
3. US Census Bureau Gazetteer, county subdivisions (New England and New Jersey towns).
4. GeoNames populated places (CC BY 4.0), for small unincorporated communities.

Every Census place is written out, so ``City, ST`` queries for any US town resolve
locally. Rows from the other sources are written only for station cities that need them.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from fuelroute.core.errors import DataFileError
from fuelroute.core.locations import US_STATE_CODES
from fuelroute.core.places import place_key

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

__all__ = [
    "PLACE_COLUMNS",
    "PlaceBuild",
    "PlaceRecord",
    "PlaceSource",
    "build_places",
    "census_place_names",
    "read_census_gazetteer",
    "read_geonames",
    "read_place_aliases",
    "read_places",
    "write_places",
]

PLACE_COLUMNS = ("name", "state", "latitude", "longitude", "source")

type _Key = tuple[str, str]

# Census names end with a legal/statistical area description ("Abbeville city",
# "Autaugaville CCD"). Longest first, removed once, so "Boise City city" keeps "Boise City".
_AREA_SUFFIXES = sorted(
    (
        "city and borough",
        "consolidated government",
        "metropolitan government",
        "metro government",
        "unified government",
        "urban county",
        "charter township",
        "municipality",
        "plantation",
        "comunidad",
        "zona urbana",
        "township",
        "borough",
        "village",
        "purchase",
        "location",
        "city",
        "town",
        "gore",
        "grant",
        "CDP",
        "CCD",
        "UT",
    ),
    key=len,
    reverse=True,
)
_CONSOLIDATED_SUFFIXES = frozenset(
    {
        "consolidated government",
        "metropolitan government",
        "metro government",
        "unified government",
        "urban county",
    }
)
_LEADING = re.compile(r"^(town|city|village|borough) of ", re.IGNORECASE)
_CONSOLIDATED_NAME = re.compile(r"^([^-/]+)[-/].+ County$")
_GEONAMES_POPULATED_PLACE = "P"
_GEONAMES_MIN_COLUMNS = 15


class PlaceSource(StrEnum):
    """The dataset a place's coordinates come from."""

    ALIAS = "alias"
    CENSUS_PLACE = "census_place"
    CENSUS_COUNTY_SUBDIVISION = "census_county_subdivision"
    GEONAMES = "geonames"


@dataclass(frozen=True, slots=True)
class PlaceRecord:
    """A named point in one state."""

    name: str
    state: str
    latitude: float
    longitude: float
    source: PlaceSource

    @property
    def key(self) -> tuple[str, str]:
        """Return the lookup key: the normalised name and the state code."""
        return (place_key(self.name), self.state)


@dataclass(frozen=True, slots=True)
class PlaceBuild:
    """The place list and the station cities it could not place."""

    places: tuple[PlaceRecord, ...]
    unmatched: tuple[tuple[str, str], ...]
    matched_by_source: dict[PlaceSource, int]


def census_place_names(raw: str) -> tuple[str, tuple[str, ...]]:
    """Return the plain name of a Census area and short names it is also known by.

    >>> census_place_names("Nashville-Davidson metropolitan government (balance)")
    ('Nashville-Davidson', ('Nashville',))
    """
    balance = "(balance)" in raw
    name = _LEADING.sub("", raw.replace("(balance)", "").strip())
    suffix = next((s for s in _AREA_SUFFIXES if name.endswith(f" {s}")), None)
    if suffix is not None:
        name = name[: -len(suffix) - 1].strip()
    consolidated = balance or suffix in _CONSOLIDATED_SUFFIXES
    aliases: tuple[str, ...] = ()
    if consolidated or _CONSOLIDATED_NAME.match(name):
        short = re.split(r"[-/]", name, maxsplit=1)[0].strip()
        if short != name:
            aliases = (short,)
    return name, aliases


def read_census_gazetteer(
    path: Path, *, source: PlaceSource
) -> Iterator[tuple[PlaceRecord, tuple[str, ...]]]:
    """Yield each area of a Census Gazetteer file with its short names.

    Raises:
        DataFileError: the file cannot be read or lacks the expected columns.
    """
    for row in _read_rows(path, delimiter="|", required=("USPS", "NAME", "INTPTLAT", "INTPTLONG")):
        state = row["USPS"]
        if state not in US_STATE_CODES:
            continue
        name, aliases = census_place_names(row["NAME"])
        record = PlaceRecord(
            name=name,
            state=state,
            latitude=float(row["INTPTLAT"]),
            longitude=float(row["INTPTLONG"]),
            source=source,
        )
        yield record, aliases


def read_geonames(path: Path) -> dict[_Key, PlaceRecord]:
    """Return the most populous GeoNames populated place for each name and state.

    Raises:
        DataFileError: the file cannot be read.
    """
    best: dict[_Key, tuple[int, PlaceRecord]] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                columns = line.rstrip("\n").split("\t")
                if len(columns) < _GEONAMES_MIN_COLUMNS:
                    continue
                if columns[6] != _GEONAMES_POPULATED_PLACE or columns[10] not in US_STATE_CODES:
                    continue
                record = PlaceRecord(
                    name=columns[2] or columns[1],
                    state=columns[10],
                    latitude=float(columns[4]),
                    longitude=float(columns[5]),
                    source=PlaceSource.GEONAMES,
                )
                population = int(columns[14] or 0)
                current = best.get(record.key)
                if current is None or population > current[0]:
                    best[record.key] = (population, record)
    except OSError as error:
        msg = f"Cannot read GeoNames file {path}: {error.strerror or error}."
        raise DataFileError(msg) from error
    return {key: record for key, (_, record) in best.items()}


def read_place_aliases(path: Path) -> list[PlaceRecord]:
    """Return the hand-checked places in an alias file.

    Raises:
        DataFileError: the file cannot be read or a row is malformed.
    """
    required = ("name", "state", "latitude", "longitude", "note")
    return [
        _place(row, PlaceSource.ALIAS, f"{path}") for row in _read_rows(path, required=required)
    ]


def read_places(path: Path) -> list[PlaceRecord]:
    """Return the places in a file written by ``write_places``.

    Raises:
        DataFileError: the file cannot be read or a row is malformed.
    """
    places: list[PlaceRecord] = []
    for row in _read_rows(path, required=PLACE_COLUMNS):
        try:
            source = PlaceSource(row["source"])
        except ValueError as error:
            msg = f"{path}: unknown place source {row['source']!r}."
            raise DataFileError(msg) from error
        places.append(_place(row, source, f"{path}"))
    return places


def write_places(path: Path, places: Iterable[PlaceRecord]) -> None:
    """Write places sorted by state and name, so a rebuild gives the same bytes."""
    ordered = sorted(places, key=lambda p: (p.state, p.name, p.source))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(PLACE_COLUMNS)
        for place in ordered:
            writer.writerow(
                (
                    place.name,
                    place.state,
                    f"{place.latitude:.6f}",
                    f"{place.longitude:.6f}",
                    place.source.value,
                )
            )


def build_places(
    *,
    census_places: Iterable[tuple[PlaceRecord, tuple[str, ...]]],
    census_county_subdivisions: Iterable[tuple[PlaceRecord, tuple[str, ...]]],
    geonames: dict[_Key, PlaceRecord],
    aliases: Iterable[PlaceRecord],
    station_cities: Iterable[tuple[str, str]],
) -> PlaceBuild:
    """Return every Census place plus a row for each station city that needs another source."""
    census = list(census_places)
    places = _first_by_key(record for record, _ in census)
    tiers: list[tuple[PlaceSource, dict[_Key, PlaceRecord]]] = [
        (PlaceSource.ALIAS, _first_by_key(aliases)),
        (PlaceSource.CENSUS_PLACE, places),
        (PlaceSource.CENSUS_PLACE, _short_names(census)),
        (PlaceSource.CENSUS_COUNTY_SUBDIVISION, _with_short_names(census_county_subdivisions)),
        (PlaceSource.GEONAMES, geonames),
    ]
    output = dict(places)
    unmatched: list[tuple[str, str]] = []
    matched_by_source: dict[PlaceSource, int] = dict.fromkeys(PlaceSource, 0)
    for city, state in sorted(set(station_cities)):
        key = (place_key(city), state)
        for source, table in tiers:
            found = table.get(key)
            if found is not None:
                matched_by_source[source] += 1
                if output.get(key) is not found:
                    output[key] = PlaceRecord(
                        city, state, found.latitude, found.longitude, found.source
                    )
                break
        else:
            unmatched.append((city, state))
    return PlaceBuild(
        places=tuple(output.values()),
        unmatched=tuple(unmatched),
        matched_by_source=matched_by_source,
    )


def _first_by_key(records: Iterable[PlaceRecord]) -> dict[_Key, PlaceRecord]:
    table: dict[_Key, PlaceRecord] = {}
    for record in records:
        table.setdefault(record.key, record)
    return table


def _short_names(
    entries: Iterable[tuple[PlaceRecord, tuple[str, ...]]],
) -> dict[_Key, PlaceRecord]:
    table: dict[_Key, PlaceRecord] = {}
    for record, aliases in entries:
        for alias in aliases:
            table.setdefault((place_key(alias), record.state), record)
    return table


def _with_short_names(
    entries: Iterable[tuple[PlaceRecord, tuple[str, ...]]],
) -> dict[_Key, PlaceRecord]:
    listed = list(entries)
    table = _first_by_key(record for record, _ in listed)
    for key, record in _short_names(listed).items():
        table.setdefault(key, record)
    return table


def _place(row: dict[str, str], source: PlaceSource, where: str) -> PlaceRecord:
    try:
        latitude, longitude = float(row["latitude"]), float(row["longitude"])
    except ValueError as error:
        msg = f"{where}: bad coordinates in {row!r}."
        raise DataFileError(msg) from error
    if row["state"] not in US_STATE_CODES or not row["name"]:
        msg = f"{where}: a place needs a name and a US state code; got {row!r}."
        raise DataFileError(msg)
    return PlaceRecord(row["name"], row["state"], latitude, longitude, source)


def _read_rows(
    path: Path, *, required: tuple[str, ...], delimiter: str = ","
) -> Iterator[dict[str, str]]:
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            columns = {name.strip() for name in reader.fieldnames or ()}
            missing = [name for name in required if name not in columns]
            if missing:
                msg = f"{path}: missing columns {', '.join(missing)}."
                raise DataFileError(msg)
            for row in reader:
                yield {key.strip(): (value or "").strip() for key, value in row.items() if key}
    except OSError as error:
        msg = f"Cannot read {path}: {error.strerror or error}."
        raise DataFileError(msg) from error
