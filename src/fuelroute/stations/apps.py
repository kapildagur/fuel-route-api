"""Django configuration for the stations app."""

from __future__ import annotations

from django.apps import AppConfig

__all__ = ["StationsConfig"]


class StationsConfig(AppConfig):
    """Stores fuel stations and places."""

    name = "fuelroute.stations"
    label = "stations"
    verbose_name = "Fuel stations"
