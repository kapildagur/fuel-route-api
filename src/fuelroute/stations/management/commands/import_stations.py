"""``manage.py import_stations``: load the place list and the fuel price file."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fuelroute.core.errors import FuelRouteError
from fuelroute.stations.repository import import_station_data

if TYPE_CHECKING:
    from argparse import ArgumentParser

__all__ = ["Command"]


class Command(BaseCommand):
    """Replace the stations and places in the database with the data files."""

    help = "Load data/places.csv and data/fuel-prices.csv into the database."

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Accept paths to the two files, defaulting to FUELROUTE_DATA_DIR."""
        data_dir = Path(settings.FUELROUTE_DATA_DIR)
        parser.add_argument("--prices", type=Path, default=data_dir / "fuel-prices.csv")
        parser.add_argument("--places", type=Path, default=data_dir / "places.csv")

    def handle(self, *_args: Any, **options: Any) -> None:  # noqa: ANN401  # Django's command signature
        """Run the import and print what was loaded and what was left out."""
        try:
            report = import_station_data(
                prices_path=options["prices"], places_path=options["places"]
            )
        except FuelRouteError as error:
            raise CommandError(str(error)) from error

        self.stdout.write(
            f"Read {report.rows_read} price rows: {report.non_us_rows} outside the USA, "
            f"{report.duplicate_rows} repeated station IDs (lowest price kept)."
        )
        self.stdout.write(f"Imported {report.places_imported} places.")
        for station_id, city, state in report.unlocated:
            self.stderr.write(f"Station {station_id} left out: no place for {city}, {state}.")
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {report.stations_imported} stations; "
                f"{len(report.unlocated)} left out without a known town."
            )
        )
