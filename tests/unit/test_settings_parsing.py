from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from fuelroute import settings as project_settings


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("TRUE", True), (" yes ", True), ("on", True), ("0", False), ("off", False)],
)
def test_boolean_settings_accept_common_spellings(
    monkeypatch: pytest.MonkeyPatch, value: str, *, expected: bool
) -> None:
    monkeypatch.setenv("FLAG", value)
    assert project_settings._env_bool("FLAG", default=not expected) is expected


@pytest.mark.parametrize("value", [None, "", "  "])
def test_missing_boolean_setting_uses_the_default(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("FLAG", raising=False)
    else:
        monkeypatch.setenv("FLAG", value)
    assert project_settings._env_bool("FLAG", default=True) is True


def test_unreadable_boolean_setting_stops_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FLAG", "maybe")
    with pytest.raises(ImproperlyConfigured, match="FLAG must be true or false"):
        project_settings._env_bool("FLAG", default=False)


def test_number_setting_within_bounds_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIZE", "12.5")
    assert project_settings._env_float("SIZE", default=1, minimum=0, maximum=20) == 12.5


def test_missing_number_setting_uses_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIZE", raising=False)
    assert project_settings._env_float("SIZE", default=3, minimum=0, maximum=20) == 3


@pytest.mark.parametrize("value", ["-1", "21", "big", "nan"])
def test_number_setting_out_of_bounds_stops_the_process(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SIZE", value)
    with pytest.raises(ImproperlyConfigured, match="SIZE must be a number from 0 to 20"):
        project_settings._env_float("SIZE", default=1, minimum=0, maximum=20)


def test_list_setting_drops_blank_items(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOSTS", " a.example , ,b.example,")
    assert project_settings._env_list("HOSTS", default="") == ["a.example", "b.example"]


def test_without_redis_both_caches_live_in_process_memory() -> None:
    caches = project_settings._caches("")
    assert {alias: cache["BACKEND"] for alias, cache in caches.items()} == {
        "default": "django.core.cache.backends.locmem.LocMemCache",
        "routes": "django.core.cache.backends.locmem.LocMemCache",
    }


def test_redis_url_moves_both_caches_to_redis_with_short_timeouts() -> None:
    caches = project_settings._caches("redis://cache:6379/0")
    for alias in ("default", "routes"):
        assert caches[alias]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"
        assert caches[alias]["LOCATION"] == "redis://cache:6379/0"
        assert caches[alias]["KEY_PREFIX"] == f"fuelroute-{alias}"
        assert caches[alias]["OPTIONS"] == {"socket_connect_timeout": 0.5, "socket_timeout": 0.5}


def test_redis_url_with_another_scheme_stops_the_process() -> None:
    with pytest.raises(ImproperlyConfigured, match="REDIS_URL must start with redis://"):
        project_settings._caches("http://cache:6379")


def test_without_a_database_url_the_database_is_a_sqlite_file() -> None:
    databases = project_settings._databases("", "/srv/fuelroute.sqlite3")
    assert databases == {
        "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "/srv/fuelroute.sqlite3"}
    }


def test_database_url_selects_postgresql_with_kept_and_checked_connections() -> None:
    databases = project_settings._databases(
        "postgres://fuel:secret@db.internal:5433/fuelroute", "/unused"
    )
    default = databases["default"]
    assert default["ENGINE"] == "django.db.backends.postgresql"
    assert (default["HOST"], default["PORT"], default["NAME"]) == ("db.internal", 5433, "fuelroute")
    assert (default["USER"], default["PASSWORD"]) == ("fuel", "secret")
    assert default["CONN_MAX_AGE"] == 60
    assert default["CONN_HEALTH_CHECKS"] is True


@pytest.mark.parametrize("url", ["mysql://fuel@db/fuelroute", "sqlite:///tmp/x.db"])
def test_database_url_other_than_postgresql_stops_the_process(url: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="must be a PostgreSQL URL"):
        project_settings._databases(url, "/unused")
