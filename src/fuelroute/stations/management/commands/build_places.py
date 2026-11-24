"""``manage.py build_places``: rebuild data/places.csv from the public gazetteers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fuelroute.core.errors import FuelRouteError
from fuelroute.data.fuel_prices import read_fuel_prices, select_us_stations
from fuelroute.data.gazetteer import (
    PlaceSource,
    build_places,
    read_census_gazetteer,
    read_geonames,
    read_place_aliases,
    write_places,
)

if TYPE_CHECKING:
    from argparse import ArgumentParser

__all__ = ["Command"]


class Command(BaseCommand):
    """Combine the Census and GeoNames files into the committed place list."""

    help = (
        "Build data/places.csv from the Census Gazetteer places and county subdivisions "
        "files and the GeoNames US dump. `make places` downloads them."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Accept the three downloaded files and the committed inputs and output."""
        data_dir = Path(settings.FUELROUTE_DATA_DIR)
        parser.add_argument("--census-places", type=Path, required=True)
        parser.add_argument("--census-county-subdivisions", type=Path, required=True)
        parser.add_argument("--geonames", type=Path, required=True)
        parser.add_argument("--aliases", type=Path, default=data_dir / "place-aliases.csv")
        parser.add_argument("--prices", type=Path, default=data_dir / "fuel-prices.csv")
        parser.add_argument("--output", type=Path, default=data_dir / "places.csv")

    def handle(self, *_args: Any, **options: Any) -> None:  # noqa: ANN401  # Django's command signature
        """Build the list, write it, and report each source's share."""
        try:
            selection = select_us_stations(read_fuel_prices(options["prices"]))
            build = build_places(
                census_places=read_census_gazetteer(
                    options["census_places"], source=PlaceSource.CENSUS_PLACE
                ),
                census_county_subdivisions=read_census_gazetteer(
                    options["census_county_subdivisions"],
                    source=PlaceSource.CENSUS_COUNTY_SUBDIVISION,
                ),
                geonames=read_geonames(options["geonames"]),
                aliases=read_place_aliases(options["aliases"]),
                station_cities={(record.city, record.state) for record in selection.records},
            )
        except FuelRouteError as error:
            raise CommandError(str(error)) from error

        write_places(options["output"], build.places)
        for source, count in build.matched_by_source.items():
            self.stdout.write(f"Station towns matched by {source.value}: {count}")
        for city, state in build.unmatched:
            self.stderr.write(f"No coordinates for {city}, {state}; add it to the alias file.")
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {len(build.places)} places to {options['output']}.")
        )
