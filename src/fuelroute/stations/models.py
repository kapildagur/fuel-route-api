"""Database tables for fuel stations and US places."""

from __future__ import annotations

from typing import ClassVar

from django.db import models

__all__ = ["FuelStationModel", "PlaceModel"]


class PlaceModel(models.Model):
    """A US city or town with the point used for it."""

    name = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    search_key = models.CharField(max_length=120, help_text="place_key() of the name")
    latitude = models.FloatField()
    longitude = models.FloatField()
    source = models.CharField(max_length=32)

    class Meta:
        db_table = "place"
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["state", "search_key"], name="place_unique_key"),
        ]

    def __str__(self) -> str:
        """Return ``Name, ST``."""
        return f"{self.name}, {self.state}"


class FuelStationModel(models.Model):
    """A truck stop with its retail diesel price and the point of its town."""

    station_id = models.PositiveIntegerField(unique=True, help_text="OPIS Truckstop ID")
    name = models.CharField(max_length=120)
    address = models.CharField(max_length=200)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField()
    price_per_gallon = models.DecimalField(max_digits=12, decimal_places=8)
    latitude = models.FloatField()
    longitude = models.FloatField()
    location_source = models.CharField(max_length=32)

    class Meta:
        db_table = "fuel_station"
        ordering: ClassVar = ["station_id"]

    def __str__(self) -> str:
        """Return the station name and town."""
        return f"{self.name} ({self.city}, {self.state})"
