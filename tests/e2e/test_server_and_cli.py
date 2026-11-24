"""The real server and the command line, run as subprocesses against the committed data."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from tests.helpers import fixture_payload

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import FakeOpenRouteService

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
STARTUP_SECONDS = 60
MAX_CROSS_COUNTRY_RESPONSE_BYTES = 64 * 1024


def _environment(database: Path, ors_url: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "ORS_", "FUELROUTE_", "DATABASE_", "REDIS_"))
    }
    environment.update(
        {
            "DJANGO_SETTINGS_MODULE": "fuelroute.settings",
            "DJANGO_SECRET_KEY": "e2e-only-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz",
            "DJANGO_ALLOWED_HOSTS": "127.0.0.1",
            "DATABASE_PATH": str(database),
            "ORS_API_KEY": "e2e-api-key",
            "ORS_BASE_URL": ors_url,
            "FUELROUTE_LOG_LEVEL": "WARNING",
        }
    )
    return environment


def _manage(*arguments: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # fixed arguments, no shell
        [sys.executable, str(ROOT / "manage.py"), *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@pytest.fixture
def loaded_database(tmp_path: Path, fake_ors: FakeOpenRouteService) -> dict[str, str]:
    """Migrate a fresh database and import the committed data through the command line."""
    environment = _environment(tmp_path / "e2e.sqlite3", fake_ors.base_url)
    migrate = _manage("migrate", "--no-input", environment=environment)
    assert migrate.returncode == 0, migrate.stderr
    imported = _manage("import_stations", environment=environment)
    assert imported.returncode == 0, imported.stderr
    assert "Imported 6626 stations; 0 left out without a known town." in imported.stdout
    return environment


@pytest.fixture
def server(loaded_database: dict[str, str]) -> Iterator[str]:
    """Start gunicorn on a free port and return its base URL once it answers."""
    port = _free_port()
    process = subprocess.Popen(  # noqa: S603  # fixed arguments, no shell
        [
            sys.executable,
            "-m",
            "gunicorn",
            "fuelroute.wsgi:application",
            "--bind",
            f"127.0.0.1:{port}",
            "--workers",
            "1",
        ],
        cwd=ROOT,
        env=loaded_database,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + STARTUP_SECONDS
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base_url}/healthz", timeout=1).status_code == HTTPStatus.OK:
                    break
            except httpx.TransportError:
                time.sleep(0.2)
        else:
            process.terminate()
            output, _ = process.communicate(timeout=10)
            pytest.fail(f"gunicorn did not start:\n{output}")
        yield base_url
    finally:
        process.terminate()
        # communicate() also closes the output pipe, which warnings-as-errors would flag.
        process.communicate(timeout=10)


def test_server_plans_chicago_to_dallas_over_http(
    server: str, fake_ors: FakeOpenRouteService
) -> None:
    fake_ors.route_payload = fixture_payload("route-chicago-dallas.json")
    response = httpx.get(
        f"{server}/api/v1/fuel-plan",
        params={"start": "Chicago, IL", "finish": "Dallas, TX"},
        timeout=30,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    body = response.json()
    assert body["start"]["source"] == "place_directory"
    assert body["route"]["distance_miles"] == pytest.approx(968.3, abs=0.1)
    assert body["summary"]["fuel_stop_count"] >= 1
    assert body["summary"]["stations_considered"] > 100
    assert (
        body["summary"]["total_fuel_cost"] >= body["summary"]["lowest_cost_plan"]["total_fuel_cost"]
    )
    assert body["summary"]["total_fuel_cost"] == pytest.approx(
        sum(stop["cost"] for stop in body["fuel_stops"])
    )
    for stop in body["fuel_stops"]:
        assert stop["distance_from_route_miles"] <= 5.0
        assert stop["state"] in {"IL", "MO", "AR", "OK", "TX"}
    assert fake_ors.calls == [("POST", "/v2/directions/driving-hgv/geojson")]

    again = httpx.get(
        f"{server}/api/v1/fuel-plan",
        params={"start": "Chicago, IL", "finish": "Dallas, TX"},
        timeout=30,
    )
    assert again.json()["summary"] == body["summary"]
    assert len(fake_ors.calls) == 1


def test_cross_country_response_stays_lean(server: str, fake_ors: FakeOpenRouteService) -> None:
    fake_ors.route_payload = fixture_payload("route-new-york-los-angeles.json")
    response = httpx.get(
        f"{server}/api/v1/fuel-plan",
        params={"start": "New York, NY", "finish": "Los Angeles, CA"},
        timeout=30,
    )
    assert response.status_code == HTTPStatus.OK, response.text
    # NFR-08: the full 15,822-point line would make this response about 340 KB.
    assert len(response.content) <= MAX_CROSS_COUNTRY_RESPONSE_BYTES
    line = response.json()["map"]["features"][0]["geometry"]["coordinates"]
    assert len(line) < 3000


def test_server_serves_the_map_page_and_rejects_bad_input(server: str) -> None:
    page = httpx.get(f"{server}/map/", timeout=10)
    assert page.status_code == HTTPStatus.OK
    assert "Content-Security-Policy" in page.headers
    bad = httpx.get(f"{server}/api/v1/fuel-plan", params={"start": "Chicago, IL"}, timeout=10)
    assert bad.status_code == HTTPStatus.BAD_REQUEST
    assert bad.headers["Content-Type"] == "application/problem+json"


def test_server_refuses_to_start_without_an_api_key(loaded_database: dict[str, str]) -> None:
    environment = {**loaded_database, "ORS_API_KEY": ""}
    result = subprocess.run(  # fixed arguments, no shell
        [sys.executable, "-c", "import fuelroute.wsgi"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode != 0
    assert "Set ORS_API_KEY" in result.stderr


def test_import_command_reports_a_missing_file(tmp_path: Path) -> None:
    environment = _environment(tmp_path / "cli.sqlite3", "http://127.0.0.1:9")
    assert _manage("migrate", "--no-input", environment=environment).returncode == 0
    result = _manage(
        "import_stations", "--prices", str(tmp_path / "absent.csv"), environment=environment
    )
    assert result.returncode == 1
    assert "absent.csv: No such file or directory" in result.stderr
