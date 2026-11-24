"""Reading and cleaning the OPIS truck stop retail price file."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from fuelroute.core.errors import DataFileError
from fuelroute.core.locations import US_STATE_CODES

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "FUEL_PRICE_COLUMNS",
    "FuelPriceRecord",
    "StationSelection",
    "read_fuel_prices",
    "select_us_stations",
]

FUEL_PRICE_COLUMNS = (
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
)

_MAX_PRICE = Decimal(100)
"""No retail diesel price reaches $100 a gallon, so a larger value is a broken row."""


@dataclass(frozen=True, slots=True)
class FuelPriceRecord:
    """One row of the price file with its whitespace collapsed."""

    station_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    price_per_gallon: Decimal


@dataclass(frozen=True, slots=True)
class StationSelection:
    """The US stations kept from a price file and what was left out."""

    records: tuple[FuelPriceRecord, ...]
    rows_read: int
    non_us_rows: int
    duplicate_rows: int


def read_fuel_prices(path: Path) -> list[FuelPriceRecord]:
    """Return every row of the price file.

    Raises:
        DataFileError: the file cannot be read, its header differs from
            ``FUEL_PRICE_COLUMNS``, or a row holds a bad value; the message names the
            file and the line.
    """
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return list(_parse(csv.reader(handle), path))
    except OSError as error:
        msg = f"Cannot read fuel price file {path}: {error.strerror or error}."
        raise DataFileError(msg) from error


def select_us_stations(records: Iterable[FuelPriceRecord]) -> StationSelection:
    """Keep US rows only and the lowest price for each station ID.

    A station ID repeats when the source lists more than one price for it. The lowest
    is what a driver pays, so it wins; on a tie the first row wins.
    """
    rows_read = 0
    non_us_rows = 0
    cheapest: dict[int, FuelPriceRecord] = {}
    for record in records:
        rows_read += 1
        if record.state not in US_STATE_CODES:
            non_us_rows += 1
            continue
        current = cheapest.get(record.station_id)
        if current is None or record.price_per_gallon < current.price_per_gallon:
            cheapest[record.station_id] = record
    kept = tuple(cheapest[key] for key in sorted(cheapest))
    return StationSelection(
        records=kept,
        rows_read=rows_read,
        non_us_rows=non_us_rows,
        duplicate_rows=rows_read - non_us_rows - len(kept),
    )


def _parse(rows: Iterable[list[str]], path: Path) -> Iterable[FuelPriceRecord]:
    iterator = iter(rows)
    header = next(iterator, None)
    if header is None or tuple(_clean(cell) for cell in header) != FUEL_PRICE_COLUMNS:
        msg = f"{path}: the header must be {', '.join(FUEL_PRICE_COLUMNS)}; got {header!r}."
        raise DataFileError(msg)
    for line_number, row in enumerate(iterator, start=2):
        if not any(cell.strip() for cell in row):
            continue
        yield _record(row, f"{path}:{line_number}")


def _record(row: list[str], where: str) -> FuelPriceRecord:
    if len(row) != len(FUEL_PRICE_COLUMNS):
        msg = f"{where}: expected {len(FUEL_PRICE_COLUMNS)} columns, got {len(row)}."
        raise DataFileError(msg)
    station_id, name, address, city, state, rack_id, price = (_clean(cell) for cell in row)
    if not name or not city or len(state) != 2:  # noqa: PLR2004  # USPS and Canada Post codes have two letters
        msg = f"{where}: name, city and a two-letter state are required; got {row!r}."
        raise DataFileError(msg)
    return FuelPriceRecord(
        station_id=_positive_int(station_id, "OPIS Truckstop ID", where),
        name=name,
        address=address,
        city=city,
        state=state.upper(),
        rack_id=_positive_int(rack_id, "Rack ID", where),
        price_per_gallon=_price(price, where),
    )


def _positive_int(text: str, column: str, where: str) -> int:
    if not text.isdigit() or int(text) <= 0:
        msg = f"{where}: {column} must be a positive whole number, got {text!r}."
        raise DataFileError(msg)
    return int(text)


def _price(text: str, where: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        value = Decimal("NaN")
    if not value.is_finite() or not Decimal(0) < value < _MAX_PRICE:
        msg = f"{where}: Retail Price must be a number between 0 and {_MAX_PRICE}, got {text!r}."
        raise DataFileError(msg)
    return value


def _clean(text: str) -> str:
    return " ".join(text.split())
