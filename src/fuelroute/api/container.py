"""Builds the one fuel plan service a process uses, from settings and the database."""

from __future__ import annotations

import functools
import logging
from decimal import Decimal

from django.conf import settings
from django.core.cache import caches

from fuelroute.api.caching import CachedGeocoder, CachedRoutingProvider
from fuelroute.core.planner import Vehicle
from fuelroute.core.service import FuelPlanService
from fuelroute.providers.openrouteservice import OpenRouteServiceClient
from fuelroute.stations.repository import DatabasePlaceDirectory, load_station_index

__all__ = ["get_fuel_plan_service", "reset_fuel_plan_service"]

logger = logging.getLogger(__name__)


@functools.cache
def get_fuel_plan_service() -> FuelPlanService:
    """Return the process-wide service, building the station index on first use.

    The service and everything it holds are immutable after construction, so threads
    share it without locks. ``fuelroute.startup`` calls this at boot, so the first
    request does not pay for loading the stations.
    """
    client = OpenRouteServiceClient(
        api_key=settings.FUELROUTE_ORS_API_KEY,
        base_url=settings.FUELROUTE_ORS_BASE_URL,
        profile=settings.FUELROUTE_ORS_PROFILE,
        timeout_seconds=settings.FUELROUTE_ORS_TIMEOUT_SECONDS,
    )
    cache = caches["routes"]
    stations = load_station_index()
    logger.info("station index built: stations=%d", len(stations))
    return FuelPlanService(
        routing=CachedRoutingProvider(
            client,
            cache,
            namespace=f"ors:{client.profile}",
            timeout_seconds=settings.FUELROUTE_CACHE_SECONDS,
        ),
        geocoder=CachedGeocoder(client, cache, timeout_seconds=settings.FUELROUTE_CACHE_SECONDS),
        places=DatabasePlaceDirectory(),
        stations=stations,
        vehicle=Vehicle(
            tank_gallons=settings.FUELROUTE_TANK_GALLONS,
            miles_per_gallon=settings.FUELROUTE_MILES_PER_GALLON,
        ),
        corridor_miles=settings.FUELROUTE_CORRIDOR_MILES,
        min_stop_saving=Decimal(str(settings.FUELROUTE_MIN_STOP_SAVING)),
    )


def reset_fuel_plan_service() -> None:
    """Drop the built service, so the next call reads settings and the database again."""
    get_fuel_plan_service.cache_clear()
