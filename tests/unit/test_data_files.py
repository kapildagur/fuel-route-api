from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest

from fuelroute.core.errors import DataFileError
from fuelroute.data.fuel_prices import (
    FUEL_PRICE_COLUMNS,
    FuelPriceRecord,
    read_fuel_prices,
    select_us_stations,
)
from fuelroute.data.gazetteer import (
    PlaceRecord,
    PlaceSource,
    build_places,
    census_place_names,
    read_census_gazetteer,
    read_geonames,
    read_place_aliases,
    read_places,
    write_places,
)

if TYPE_CHECKING:
    from pathlib import Path

HEADER = ",".join(FUEL_PRICE_COLUMNS)


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _record(station_id: int, price: str, state: str = "TX") -> FuelPriceRecord:
    return FuelPriceRecord(station_id, "Stop", "I-35", "Austin", state, 1, Decimal(price))


# ---------------------------------------------------------------- fuel price file


def test_rows_are_read_with_whitespace_collapsed(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "prices.csv",
        f'{HEADER}\n7,WOODSHED OF BIG CABIN,"I-44,  EXIT 283",Big Cabin   ,ok,307,3.00733333\n',
    )
    (record,) = read_fuel_prices(path)
    assert record == FuelPriceRecord(
        7, "WOODSHED OF BIG CABIN", "I-44, EXIT 283", "Big Cabin", "OK", 307, Decimal("3.00733333")
    )


def test_byte_order_mark_and_blank_lines_are_tolerated(tmp_path: Path) -> None:
    path = _write(tmp_path / "prices.csv", f"﻿{HEADER}\n\n1,A,B,C,TX,2,3.1\n\n")
    assert len(read_fuel_prices(path)) == 1


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match=r"missing\.csv"):
        read_fuel_prices(tmp_path / "missing.csv")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "the header must be"),
        ("a,b,c\n", "the header must be"),
        (f"{HEADER}\n1,A,B,C,TX,2\n", "expected 7 columns"),
        (f"{HEADER}\nx,A,B,C,TX,2,3.1\n", "OPIS Truckstop ID must be a positive"),
        (f"{HEADER}\n0,A,B,C,TX,2,3.1\n", "OPIS Truckstop ID must be a positive"),
        (f"{HEADER}\n1,A,B,C,TX,-2,3.1\n", "Rack ID must be a positive"),
        (f"{HEADER}\n1,A,B,C,TX,2,free\n", "Retail Price must be a number"),
        (f"{HEADER}\n1,A,B,C,TX,2,0\n", "Retail Price must be a number"),
        (f"{HEADER}\n1,A,B,C,TX,2,150\n", "Retail Price must be a number"),
        (f"{HEADER}\n1,A,B,C,TX,2,NaN\n", "Retail Price must be a number"),
        (f"{HEADER}\n1,,B,C,TX,2,3.1\n", "two-letter state are required"),
        (f"{HEADER}\n1,A,B,C,Texas,2,3.1\n", "two-letter state are required"),
    ],
)
def test_malformed_file_is_rejected_with_its_line(
    tmp_path: Path, content: str, message: str
) -> None:
    path = _write(tmp_path / "prices.csv", content)
    with pytest.raises(DataFileError, match=message):
        read_fuel_prices(path)


def test_selection_keeps_us_rows_and_the_lowest_price_per_station() -> None:
    records = [
        _record(2, "3.30"),
        _record(1, "3.50"),
        _record(1, "3.40"),
        _record(1, "3.45"),
        _record(3, "4.40", state="ON"),
    ]
    selection = select_us_stations(records)
    assert [(r.station_id, r.price_per_gallon) for r in selection.records] == [
        (1, Decimal("3.40")),
        (2, Decimal("3.30")),
    ]
    assert (selection.rows_read, selection.non_us_rows, selection.duplicate_rows) == (5, 1, 2)


def test_selection_of_nothing_is_empty() -> None:
    selection = select_us_stations([])
    assert selection.records == ()
    assert selection.rows_read == 0


# ---------------------------------------------------------------- Census names


@pytest.mark.parametrize(
    ("raw", "name", "aliases"),
    [
        ("Abbeville city", "Abbeville", ()),
        ("Boise City city", "Boise City", ()),
        ("Town of Pecos city", "Pecos", ()),
        ("Indianapolis city (balance)", "Indianapolis", ()),
        (
            "Nashville-Davidson metropolitan government (balance)",
            "Nashville-Davidson",
            ("Nashville",),
        ),
        ("Lexington-Fayette urban county", "Lexington-Fayette", ("Lexington",)),
        (
            "Augusta-Richmond County consolidated government (balance)",
            "Augusta-Richmond County",
            ("Augusta",),
        ),
        ("Macon-Bibb County", "Macon-Bibb County", ("Macon",)),
        (
            "Louisville/Jefferson County metro government (balance)",
            "Louisville/Jefferson County",
            ("Louisville",),
        ),
        ("Winston-Salem city", "Winston-Salem", ()),
        ("Autaugaville CCD", "Autaugaville", ()),
        ("Mahwah township", "Mahwah", ()),
        ("Abanda CDP", "Abanda", ()),
    ],
)
def test_census_names_lose_their_area_description(
    raw: str, name: str, aliases: tuple[str, ...]
) -> None:
    assert census_place_names(raw) == (name, aliases)


# ---------------------------------------------------------------- gazetteer files


def _census(tmp_path: Path, name: str, rows: list[tuple[str, str, float, float]]) -> Path:
    lines = ["USPS|GEOID|NAME|INTPTLAT|INTPTLONG                                 "]
    lines += [f"{state}|1|{place}|{lat}|{lon}" for state, place, lat, lon in rows]
    return _write(tmp_path / name, "\n".join(lines) + "\n")


def _geonames(tmp_path: Path, rows: list[tuple[str, str, float, float, int, str]]) -> Path:
    lines = []
    for index, (name, state, lat, lon, population, feature_class) in enumerate(rows):
        columns = [str(index), name, name, "", str(lat), str(lon), feature_class, "PPL", "US"]
        columns += ["", state, "", "", "", str(population), "", "", "", ""]
        lines.append("\t".join(columns))
    lines.append("short\tline")
    return _write(tmp_path / "US.txt", "\n".join(lines) + "\n")


def test_census_file_yields_us_places_with_short_names(tmp_path: Path) -> None:
    path = _census(
        tmp_path,
        "places.txt",
        [
            ("TN", "Nashville-Davidson metropolitan government (balance)", 36.17, -86.78),
            ("PR", "San Juan zona urbana", 18.4, -66.1),
        ],
    )
    ((record, aliases),) = list(read_census_gazetteer(path, source=PlaceSource.CENSUS_PLACE))
    assert record == PlaceRecord(
        "Nashville-Davidson", "TN", 36.17, -86.78, PlaceSource.CENSUS_PLACE
    )
    assert aliases == ("Nashville",)


def test_census_file_without_coordinates_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path / "bad.txt", "USPS|NAME\nTX|Austin city\n")
    with pytest.raises(DataFileError, match="missing columns INTPTLAT, INTPTLONG"):
        list(read_census_gazetteer(path, source=PlaceSource.CENSUS_PLACE))


def test_geonames_keeps_the_most_populous_populated_place(tmp_path: Path) -> None:
    path = _geonames(
        tmp_path,
        [
            ("Glenmont", "NY", 42.6, -73.8, 10, "P"),
            ("Glenmont", "NY", 42.0, -74.0, 2000, "P"),
            ("Glenmont", "NY", 42.9, -73.0, 0, "P"),
            ("Glenmont Hill", "NY", 41.0, -75.0, 9000, "T"),
            ("Toronto", "08", 43.7, -79.4, 2_000_000, "P"),
        ],
    )
    places = read_geonames(path)
    assert list(places) == [("glenmont", "NY")]
    assert places["glenmont", "NY"].latitude == 42.0


def test_unreadable_geonames_file_names_the_path(tmp_path: Path) -> None:
    with pytest.raises(DataFileError, match=r"US\.txt"):
        read_geonames(tmp_path / "US.txt")


def test_alias_file_rows_become_alias_places(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "aliases.csv",
        "name,state,latitude,longitude,note\nWillow Beach,AZ,35.72,-114.40,White Hills\n",
    )
    assert read_place_aliases(path) == [
        PlaceRecord("Willow Beach", "AZ", 35.72, -114.40, PlaceSource.ALIAS)
    ]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("Willow Beach,AZ,north,-114.40,x", "bad coordinates"),
        ("Willow Beach,ON,35.72,-114.40,x", "US state code"),
        (",AZ,35.72,-114.40,x", "US state code"),
    ],
)
def test_bad_alias_rows_are_rejected(tmp_path: Path, row: str, message: str) -> None:
    path = _write(tmp_path / "aliases.csv", f"name,state,latitude,longitude,note\n{row}\n")
    with pytest.raises(DataFileError, match=message):
        read_place_aliases(path)


def test_places_round_trip_through_the_file_in_a_stable_order(tmp_path: Path) -> None:
    places = [
        PlaceRecord("Zeta", "TX", 30.0, -97.0, PlaceSource.CENSUS_PLACE),
        PlaceRecord("Alpha", "TX", 31.123456789, -98.0, PlaceSource.GEONAMES),
        PlaceRecord("Beta", "AL", 32.0, -86.0, PlaceSource.ALIAS),
    ]
    path = tmp_path / "places.csv"
    write_places(path, places)
    first = path.read_bytes()
    loaded = read_places(path)
    assert [p.name for p in loaded] == ["Beta", "Alpha", "Zeta"]
    assert loaded[1].latitude == 31.123457
    write_places(path, reversed(loaded))
    assert path.read_bytes() == first


def test_place_file_with_an_unknown_source_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path / "places.csv", "name,state,latitude,longitude,source\nA,TX,1,2,guess\n")
    with pytest.raises(DataFileError, match="unknown place source 'guess'"):
        read_places(path)


def test_build_matches_each_station_town_from_the_first_source_that_knows_it() -> None:
    census_places = [
        (PlaceRecord("Austin", "TX", 30.3, -97.7, PlaceSource.CENSUS_PLACE), ()),
        (
            PlaceRecord("Nashville-Davidson", "TN", 36.2, -86.8, PlaceSource.CENSUS_PLACE),
            ("Nashville",),
        ),
        (PlaceRecord("Hot Springs", "AR", 34.5, -93.1, PlaceSource.CENSUS_PLACE), ()),
    ]
    subdivisions = [
        (PlaceRecord("Mahwah", "NJ", 41.1, -74.2, PlaceSource.CENSUS_COUNTY_SUBDIVISION), ()),
        (PlaceRecord("Austin", "TX", 0.0, 0.0, PlaceSource.CENSUS_COUNTY_SUBDIVISION), ()),
    ]
    geonames = {
        ("breezewood", "PA"): PlaceRecord("Breezewood", "PA", 40.0, -78.2, PlaceSource.GEONAMES)
    }
    aliases = [PlaceRecord("Hot Springs National Park", "AR", 34.5, -93.1, PlaceSource.ALIAS)]
    build = build_places(
        census_places=census_places,
        census_county_subdivisions=subdivisions,
        geonames=geonames,
        aliases=aliases,
        station_cities=[
            ("Austin", "TX"),
            ("Nashville", "TN"),
            ("Mahwah", "NJ"),
            ("Breezewood", "PA"),
            ("Hot Springs National Park", "AR"),
            ("Nowhere", "WY"),
        ],
    )
    by_name = {(p.name, p.state): p for p in build.places}
    assert by_name["Austin", "TX"].latitude == 30.3
    assert by_name["Nashville", "TN"].source is PlaceSource.CENSUS_PLACE
    assert by_name["Mahwah", "NJ"].source is PlaceSource.CENSUS_COUNTY_SUBDIVISION
    assert by_name["Breezewood", "PA"].source is PlaceSource.GEONAMES
    assert by_name["Hot Springs National Park", "AR"].source is PlaceSource.ALIAS
    assert ("Nashville-Davidson", "TN") in by_name
    assert build.unmatched == (("Nowhere", "WY"),)
    assert build.matched_by_source == {
        PlaceSource.ALIAS: 1,
        PlaceSource.CENSUS_PLACE: 2,
        PlaceSource.CENSUS_COUNTY_SUBDIVISION: 1,
        PlaceSource.GEONAMES: 1,
    }
