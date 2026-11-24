"""Django settings, read from the environment once when the process starts.

A malformed number stops the process at import, so a bad deploy never serves a request.
Values that only the web server needs, such as the API key, are checked by
``fuelroute.startup`` so that ``manage.py`` commands run without them.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    normalised = value.strip().lower()
    if normalised in {"1", "true", "yes", "on"}:
        return True
    if normalised in {"0", "false", "no", "off"}:
        return False
    msg = f"{name} must be true or false, got {value!r}."
    raise ImproperlyConfigured(msg)


def _env_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    try:
        number = float(value)
    except ValueError:
        number = float("nan")
    if not minimum <= number <= maximum:
        msg = f"{name} must be a number from {minimum} to {maximum}, got {value!r}."
        raise ImproperlyConfigured(msg)
    return number


def _env_list(name: str, *, default: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = _env_bool("DJANGO_DEBUG", default=False)
# Only a debug process falls back to this key; fuelroute.startup refuses to serve without one.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "") or (
    "django-insecure-local-development-only" if DEBUG else ""
)
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "rest_framework",
    "drf_spectacular",
    "fuelroute.stations",
    "fuelroute.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fuelroute.urls"
WSGI_APPLICATION = "fuelroute.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", str(BASE_DIR / "var" / "fuelroute.sqlite3")),
    },
}

_REDIS_SCHEMES = ("redis://", "rediss://", "unix://")


def _caches(redis_url: str) -> dict[str, dict[str, object]]:
    """Return CACHES: per-process memory by default, Redis when ``redis_url`` is set.

    Request input decides the keys of both caches, so both are bounded: by entry count
    in memory, by the server's maxmemory policy in Redis. Routes are large and have
    their own cache, so rate-limit counters never push them out. Redis calls time out
    after half a second, so a slow store degrades to a cache miss instead of a stall.
    """
    if not redis_url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "fuelroute-default",
                "OPTIONS": {"MAX_ENTRIES": 10_000},
            },
            "routes": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "fuelroute-routes",
                "OPTIONS": {"MAX_ENTRIES": 256},
            },
        }
    if not redis_url.startswith(_REDIS_SCHEMES):
        msg = f"REDIS_URL must start with redis://, rediss:// or unix://, got {redis_url!r}."
        raise ImproperlyConfigured(msg)
    options = {"socket_connect_timeout": 0.5, "socket_timeout": 0.5}
    return {
        alias: {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": redis_url,
            "KEY_PREFIX": f"fuelroute-{alias}",
            "OPTIONS": options,
        }
        for alias in ("default", "routes")
    }


CACHES = _caches(os.environ.get("REDIS_URL", "").strip())

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
USE_I18N = False
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

SECURE_CONTENT_TYPE_NOSNIFF = True
# OpenStreetMap refuses tile requests without a Referer, so cross-site requests carry
# the origin (never the path or query, which can hold a street address).
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
X_FRAME_OPTIONS = "DENY"
# The map page loads Leaflet from unpkg (pinned by integrity hash) and tiles from
# OpenStreetMap; everything else comes from this server.
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF, CSP.NONCE, "https://unpkg.com"],
    "style-src": [CSP.SELF, CSP.NONCE, "https://unpkg.com"],
    "img-src": [CSP.SELF, "data:", "https://unpkg.com", "https://tile.openstreetmap.org"],
    "connect-src": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
    "base-uri": [CSP.NONE],
    "form-action": [CSP.SELF],
}

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_THROTTLE_CLASSES": ["fuelroute.api.throttling.FailOpenAnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("FUELROUTE_RATE_LIMIT", "60/minute")},
    "EXCEPTION_HANDLER": "fuelroute.api.errors.problem_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Fuel route API",
    "DESCRIPTION": "Plans the cheapest fuel stops for a truck route between two US locations.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "loggers": {
        "fuelroute": {
            "handlers": ["console"],
            "level": os.environ.get("FUELROUTE_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}

# ---------------------------------------------------------------- fuel route planner
FUELROUTE_DATA_DIR = Path(os.environ.get("FUELROUTE_DATA_DIR", str(BASE_DIR / "data")))
FUELROUTE_ORS_API_KEY = os.environ.get("ORS_API_KEY", "")
FUELROUTE_ORS_BASE_URL = os.environ.get("ORS_BASE_URL", "https://api.openrouteservice.org")
FUELROUTE_ORS_PROFILE = os.environ.get("ORS_PROFILE", "driving-hgv")
FUELROUTE_ORS_TIMEOUT_SECONDS = _env_float(
    "ORS_TIMEOUT_SECONDS", default=10.0, minimum=1.0, maximum=60.0
)
FUELROUTE_TANK_GALLONS = _env_float(
    "FUELROUTE_TANK_GALLONS", default=50.0, minimum=1.0, maximum=500.0
)
FUELROUTE_MILES_PER_GALLON = _env_float(
    "FUELROUTE_MILES_PER_GALLON", default=10.0, minimum=1.0, maximum=100.0
)
FUELROUTE_CORRIDOR_MILES = _env_float(
    "FUELROUTE_CORRIDOR_MILES", default=5.0, minimum=0.5, maximum=25.0
)
FUELROUTE_MIN_STOP_SAVING = _env_float(
    "FUELROUTE_MIN_STOP_SAVING", default=5.0, minimum=0.0, maximum=1000.0
)
# The route line in a response is simplified to within this many metres for display;
# matching always uses the full line. 0 returns the full line.
FUELROUTE_MAP_TOLERANCE_METERS = _env_float(
    "FUELROUTE_MAP_TOLERANCE_METERS", default=50.0, minimum=0.0, maximum=1000.0
)
FUELROUTE_CACHE_SECONDS = int(
    _env_float("FUELROUTE_CACHE_SECONDS", default=3600, minimum=0, maximum=86400)
)
