import asyncio
import json
from typing import Any

import httpx
import pytest

from orgraph.mcp_server.client import ApiClient
from orgraph.mcp_server.server import build_server

WS = "ws1"
PREFIX = f"/api/workspaces/{WS}"
ME = {
    "user": {"id": "u1", "email": "bruce@wayne.com", "name": "Bruce", "created_at": "t"},
    "workspaces": [{"id": WS, "name": "Wayne", "slug": "wayne", "role": "owner"}],
}


class FakeApi:
    """Stands in for the REST API: scripted responses, recorded requests."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: dict[tuple[str, str], list[tuple[int, Any]]] = {}
        self.add("GET", "/api/me", ME)

    def add(self, method: str, path: str, body: Any = None, status: int = 200) -> None:
        """Script a response. Several for one route are served in order, the
        last one repeating."""
        self.routes.setdefault((method, path), []).append((status, body))

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        queue = self.routes.get((request.method, request.url.path))
        if not queue:
            return httpx.Response(404, json={"detail": f"no route {request.url.path}"})
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        if status == 204:
            return httpx.Response(204)
        return httpx.Response(status, json=body)

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == path]


class Clock:
    """Fake time: sleeping advances it instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture
def client(api) -> ApiClient:
    return ApiClient(
        "http://api.test", "ogk_test", transport=httpx.MockTransport(api.handler)
    )


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def server(client, clock):
    return build_server(
        client, wait_timeout=60, poll_interval=2, sleep=clock.sleep, clock=clock
    )


@pytest.fixture
def call(server):
    """Invoke a tool through the MCP server and return its decoded result."""

    def _call(name: str, /, **arguments: Any) -> Any:
        result = asyncio.run(server.call_tool(name, arguments))
        assert not result.is_error
        assert json.loads(result.content[0].text) == result.structured_content
        return result.structured_content

    return _call
