from __future__ import annotations

from decimal import Decimal
from io import StringIO
from typing import TYPE_CHECKING

import pytest
from django.core.management import CommandError, call_command

from fuelroute.data.fuel_prices import FUEL_PRICE_COLUMNS
from fuelroute.stations.models import FuelStationModel, PlaceModel

if TYPE_CHECKING:
    from pathlib import Path

PRICES = (
    ",".join(FUEL_PRICE_COLUMNS)
    + "\n"
    + "1,STOP ONE,I-35 EXIT 1,Austin,TX,10,3.10\n"
    + "1,STOP ONE,I-35 EXIT 1,Austin,TX,10,3.05\n"
    + "2,STOP TWO,I-35 EXIT 2,St Louis,MO,11,3.20\n"
    + "3,STOP THREE,HWY 1,Nowhere,WY,12,3.30\n"
    + "4,CANADA STOP,HWY 401,Toronto,ON,13,4.40\n"
)
PLACES = (
    "name,state,latitude,longitude,source\n"
    "Austin,TX,30.3,-97.7,census_place\n"
    "Saint Louis,MO,38.6,-90.2,geonames\n"
)


def _files(tmp_path: Path, *, places: str = PLACES) -> tuple[Path, Path]:
    prices_path = tmp_path / "prices.csv"
    places_path = tmp_path / "places.csv"
    prices_path.write_text(PRICES, encoding="utf-8")
    places_path.write_text(places, encoding="utf-8")
    return prices_path, places_path


def _import(prices: Path, places: Path) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("import_stations", prices=prices, places=places, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


@pytest.mark.django_db
def test_import_loads_located_us_stations_and_reports_the_rest(tmp_path: Path) -> None:
    out, err = _import(*_files(tmp_path))
    stations = {s.station_id: s for s in FuelStationModel.objects.all()}
    assert set(stations) == {1, 2}
    assert stations[1].price_per_gallon == Decimal("3.05")
    assert stations[2].location_source == "geonames"
    assert PlaceModel.objects.count() == 2
    assert "Read 5 price rows: 1 outside the USA, 1 repeated station IDs" in out
    assert "Imported 2 stations; 1 left out without a known town." in out
    assert "Station 3 left out: no place for Nowhere, WY." in err


@pytest.mark.django_db
def test_import_replaces_the_previous_data(tmp_path: Path) -> None:
    files = _files(tmp_path)
    _import(*files)
    _import(*files)
    assert FuelStationModel.objects.count() == 2
    assert PlaceModel.objects.count() == 2


@pytest.mark.django_db
def test_failed_import_keeps_the_old_data(tmp_path: Path) -> None:
    _import(*_files(tmp_path))
    prices, places = _files(tmp_path, places=PLACES + "AUSTIN,TX,30.0,-97.0,census_place\n")
    with pytest.raises(CommandError, match="listed twice"):
        _import(prices, places)
    assert FuelStationModel.objects.count() == 2


@pytest.mark.django_db
def test_import_of_a_missing_file_names_it(tmp_path: Path) -> None:
    _, places = _files(tmp_path)
    with pytest.raises(CommandError, match=r"missing\.csv: No such file"):
        _import(tmp_path / "missing.csv", places)


def test_build_places_writes_the_list_and_reports_each_source(tmp_path: Path) -> None:
    census = tmp_path / "census.txt"
    census.write_text(
        "USPS|GEOID|NAME|INTPTLAT|INTPTLONG\nTX|1|Austin city|30.3|-97.7\n", encoding="utf-8"
    )
    subdivisions = tmp_path / "cousubs.txt"
    subdivisions.write_text("USPS|GEOID|NAME|INTPTLAT|INTPTLONG\n", encoding="utf-8")
    geonames = tmp_path / "US.txt"
    columns = ["1", "Saint Louis", "Saint Louis", "", "38.6", "-90.2", "P", "PPL", "US", ""]
    columns += ["MO", "", "", "", "300000", "", "", "", ""]
    geonames.write_text("\t".join(columns) + "\n", encoding="utf-8")
    aliases = tmp_path / "aliases.csv"
    aliases.write_text("name,state,latitude,longitude,note\n", encoding="utf-8")
    prices, _ = _files(tmp_path)
    output = tmp_path / "out.csv"
    out, err = StringIO(), StringIO()
    call_command(
        "build_places",
        census_places=census,
        census_county_subdivisions=subdivisions,
        geonames=geonames,
        aliases=aliases,
        prices=prices,
        output=output,
        stdout=out,
        stderr=err,
    )
    assert output.read_text(encoding="utf-8").splitlines() == [
        "name,state,latitude,longitude,source",
        "St Louis,MO,38.600000,-90.200000,geonames",
        "Austin,TX,30.300000,-97.700000,census_place",
    ]
    assert "Station towns matched by geonames: 1" in out.getvalue()
    assert "No coordinates for Nowhere, WY" in err.getvalue()


def test_build_places_with_an_unreadable_source_fails(tmp_path: Path) -> None:
    prices, _ = _files(tmp_path)
    with pytest.raises(CommandError, match="Cannot read"):
        call_command(
            "build_places",
            census_places=tmp_path / "none.txt",
            census_county_subdivisions=tmp_path / "none.txt",
            geonames=tmp_path / "none.txt",
            prices=prices,
            output=tmp_path / "out.csv",
            stdout=StringIO(),
        )
