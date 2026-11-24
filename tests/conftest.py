"""Suite-wide fixtures, and level markers taken from each test's directory."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

_LEVELS = {"unit": "unit", "integration": "integration", "e2e": "e2e", "benchmarks": "benchmark"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark each test with the level named by its directory."""
    for item in items:
        level = _LEVELS.get(Path(item.fspath).parent.name)
        if level is not None:
            item.add_marker(level)


@dataclass
class FakeOpenRouteService:
    """A local HTTP server that answers like OpenRouteService and records each call."""

    route_payload: dict[str, Any] | None = None
    route_status: int = HTTPStatus.OK
    geocode_payloads: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    authorizations: list[str] = field(default_factory=list)
    base_url: str = ""

    def respond(self, handler: BaseHTTPRequestHandler) -> tuple[int, dict[str, Any]]:
        """Return the status and body for one request."""
        url = urlparse(handler.path)
        self.calls.append((handler.command, url.path))
        self.authorizations.append(handler.headers.get("Authorization", ""))
        if handler.command == "POST" and url.path.startswith("/v2/directions/"):
            length = int(handler.headers.get("Content-Length", "0"))
            handler.rfile.read(length)
            if self.route_status != HTTPStatus.OK:
                body = {"error": {"code": 2009, "message": "Route could not be found"}}
                return self.route_status, body
            return HTTPStatus.OK, self.route_payload or {}
        if handler.command == "GET" and url.path == "/geocode/search":
            text = parse_qs(url.query).get("text", [""])[0]
            return HTTPStatus.OK, self.geocode_payloads.get(text, {"features": []})
        return HTTPStatus.NOT_FOUND, {"error": "unknown path"}


@pytest.fixture
def fake_ors() -> Iterator[FakeOpenRouteService]:
    """Run a fake OpenRouteService on a free local port for one test."""
    fake = FakeOpenRouteService()

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            status, body = fake.respond(self)
            encoded = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = _answer  # noqa: N815  # http.server dispatches on these names
        do_POST = _answer  # noqa: N815  # http.server dispatches on these names

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401  # signature fixed by http.server
            """Keep test output quiet."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fake.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield fake
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
