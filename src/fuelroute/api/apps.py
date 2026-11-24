"""Django configuration for the API app."""

from __future__ import annotations

from django.apps import AppConfig

__all__ = ["ApiConfig"]


class ApiConfig(AppConfig):
    """Serves the fuel plan endpoint, the map page and the health check."""

    name = "fuelroute.api"
    label = "api"
    verbose_name = "Fuel route API"
