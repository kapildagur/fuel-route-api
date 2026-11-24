"""URL routes of the API app."""

from __future__ import annotations

from django.urls import path
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView

from fuelroute.api.views import FuelPlanView, HealthView, MapView

__all__ = ["urlpatterns"]

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="fuel-map", permanent=False), name="home"),
    path("api/v1/fuel-plan", FuelPlanView.as_view(), name="fuel-plan"),
    path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
    path("map/", MapView.as_view(), name="fuel-map"),
    path("healthz", HealthView.as_view(), name="health"),
]
