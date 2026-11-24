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
