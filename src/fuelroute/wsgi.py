"""WSGI entry point; checks settings and loads the stations before serving."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fuelroute.settings")

application = get_wsgi_application()

from fuelroute.startup import prepare_application  # noqa: E402  # Django must be set up first

prepare_application()

__all__ = ["application"]
