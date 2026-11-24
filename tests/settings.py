"""Django settings for the test suite: fixed secrets, an in-memory database, no real provider."""

from __future__ import annotations

from fuelroute.settings import *  # noqa: F403  # the suite runs the real settings with a few overrides

SECRET_KEY = "test-only-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
# Port 9 (discard) refuses connections, so a test that forgets its fake never reaches the internet.
FUELROUTE_ORS_API_KEY = "test-api-key"
FUELROUTE_ORS_BASE_URL = "http://127.0.0.1:9"
FUELROUTE_ORS_TIMEOUT_SECONDS = 2.0
FUELROUTE_MIN_STOP_SAVING = 5.0
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405  # defined by the star import above
    "DEFAULT_THROTTLE_RATES": {"anon": "1000/minute"},
}
