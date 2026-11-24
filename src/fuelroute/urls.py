"""Root URL configuration."""

from __future__ import annotations

from django.urls import include, path

__all__ = ["urlpatterns"]

urlpatterns = [
    path("", include("fuelroute.api.urls")),
]
