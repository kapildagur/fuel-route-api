"""Checks and warm-up that run once when a server process starts."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from fuelroute.api.container import get_fuel_plan_service

__all__ = ["prepare_application"]

logger = logging.getLogger(__name__)

_INSECURE_KEY_PREFIX = "django-insecure"


def prepare_application() -> None:
    """Refuse to serve with missing settings or no stations, and build the station index.

    Raises:
        ImproperlyConfigured: the secret key or API key is missing, or no station is loaded.
    """
    if not settings.DEBUG and str(settings.SECRET_KEY).startswith(_INSECURE_KEY_PREFIX):
        msg = "Set DJANGO_SECRET_KEY to a long random value, or DJANGO_DEBUG=true for local use."
        raise ImproperlyConfigured(msg)
    if not settings.FUELROUTE_ORS_API_KEY:
        msg = "Set ORS_API_KEY to an OpenRouteService API key (free at openrouteservice.org)."
        raise ImproperlyConfigured(msg)
    service = get_fuel_plan_service()
    if service.station_count == 0:
        msg = "No fuel stations are loaded. Run `python manage.py import_stations` first."
        raise ImproperlyConfigured(msg)
    logger.info("ready: stations=%d", service.station_count)
