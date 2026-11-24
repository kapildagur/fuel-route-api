"""The shared Redis cache, against a real Redis started by Testcontainers."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import docker
import pytest
from docker.errors import DockerException
from rest_framework.throttling import AnonRateThrottle
from testcontainers.community.redis import RedisContainer

from fuelroute import settings as project_settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_django import Settings
    from rest_framework.test import APIClient

    from tests.conftest import FakeOpenRouteService

REDIS_IMAGE = "redis:8.12-alpine"
QUERY = {"start": "Westend, KS", "finish": "Eastend, KS"}

pytestmark = pytest.mark.usefixtures("road_data")


def _docker_available() -> bool:
    try:
        docker.from_env().ping()
    except (DockerException, OSError):
        return False
    return True


@pytest.fixture(scope="module")
def redis_container() -> Iterator[RedisContainer]:
    """Start one Redis for the module, or skip when Docker is not running."""
    if not _docker_available():
        pytest.skip("Docker is not available for Testcontainers")
    with RedisContainer(REDIS_IMAGE) as container:
        yield container


@pytest.fixture
def redis_url(redis_container: RedisContainer, settings: Settings) -> str:
    """Point both caches at the container, emptied, for one test."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    url = f"redis://{host}:{port}/0"
    redis_container.get_client().flushdb()
    settings.CACHES = project_settings._caches(url)
    return url


@pytest.mark.containers
def test_repeat_request_is_served_from_redis(
    api_client: APIClient,
    ors: FakeOpenRouteService,
    redis_container: RedisContainer,
    redis_url: str,
) -> None:
    del redis_url
    first = api_client.get("/api/v1/fuel-plan", QUERY)
    second = api_client.get("/api/v1/fuel-plan", QUERY)
    assert first.status_code == second.status_code == HTTPStatus.OK
    assert first.json()["summary"] == second.json()["summary"]
    assert len(ors.calls) == 1
    keys = [str(key) for key in redis_container.get_client(decode_responses=True).keys("*")]
    assert any(key.startswith("fuelroute-routes:") for key in keys)


@pytest.mark.containers
def test_rate_limit_counts_in_redis(
    api_client: APIClient,
    ors: FakeOpenRouteService,
    redis_container: RedisContainer,
    redis_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del ors, redis_url
    monkeypatch.setattr(AnonRateThrottle, "THROTTLE_RATES", {"anon": "1/minute"})
    assert api_client.get("/api/v1/fuel-plan", QUERY).status_code == HTTPStatus.OK
    assert api_client.get("/api/v1/fuel-plan", QUERY).status_code == HTTPStatus.TOO_MANY_REQUESTS
    keys = [str(key) for key in redis_container.get_client(decode_responses=True).keys("*")]
    assert any("throttle_anon" in key for key in keys)


def test_unreachable_redis_still_answers_from_the_provider(
    api_client: APIClient, ors: FakeOpenRouteService, settings: Settings
) -> None:
    # Port 9 refuses connections, as a stopped Redis would.
    settings.CACHES = project_settings._caches("redis://127.0.0.1:9/0")
    first = api_client.get("/api/v1/fuel-plan", QUERY)
    second = api_client.get("/api/v1/fuel-plan", QUERY)
    assert first.status_code == second.status_code == HTTPStatus.OK
    assert len(ors.calls) == 2
