"""MCP over streamable HTTP, served by the API process at /mcp.

Clients authenticate with a workspace API key as a bearer token:

    {"mcpServers": {"orgraph": {"type": "http", "url": "http://localhost:8000/mcp",
                                "headers": {"Authorization": "Bearer ogk_..."}}}}

One MCP server is shared by every caller; each request's key selects the
ApiClient its tools use, so a tool can only ever act as the key that called it.
"""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

import anyio
import httpx
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import Settings, get_settings
from ..security import API_KEY_PREFIX
from .client import ApiClient, ApiError
from .server import build_server

MCP_PATH = "/mcp"
_MAX_CLIENTS = 256

_current_key: ContextVar[str | None] = ContextVar("orgraph_mcp_api_key", default=None)


class KeyScopedClient:
    """Stands in for ApiClient: every call goes to the ApiClient of the API
    key that authenticated the current MCP request."""

    def __init__(self, base_url: str, *, http: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=30.0)
        self._clients: OrderedDict[str, ApiClient] = OrderedDict()
        self._lock = threading.Lock()

    def for_key(self, key: str) -> ApiClient:
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = self._clients[key] = ApiClient(self.base_url, key, client=self._http)
                while len(self._clients) > _MAX_CLIENTS:
                    self._clients.popitem(last=False)
            else:
                self._clients.move_to_end(key)
            return client

    def _current(self) -> ApiClient:
        key = _current_key.get()
        if not key:
            raise ApiError(401, "This MCP request carried no API key.")
        return self.for_key(key)

    def request(self, *args: Any, **kwargs: Any) -> Any:
        return self._current().request(*args, **kwargs)

    def ws(self, *args: Any, **kwargs: Any) -> Any:
        return self._current().ws(*args, **kwargs)

    def me(self) -> dict[str, Any]:
        return self._current().me()

    @property
    def workspace_id(self) -> str:
        return self._current().workspace_id


def _bearer(scope: Scope) -> str | None:
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
    scheme, _, token = headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return headers.get("x-api-key") or None


class BearerGate:
    """Rejects MCP requests without a valid API key and exposes the key to the
    tools for the duration of the request."""

    def __init__(self, app: ASGIApp, is_valid: Callable[[str], bool]) -> None:
        self.app, self.is_valid = app, is_valid

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        key = _bearer(scope)
        if not key:
            await self._reject(send, "Send a workspace API key as 'Authorization: Bearer ogk_...'.")
            return
        if not key.startswith(API_KEY_PREFIX) or not await anyio.to_thread.run_sync(
            self.is_valid, key
        ):
            await self._reject(send, "Invalid or revoked API key.")
            return
        token = _current_key.set(key)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_key.reset(token)

    @staticmethod
    async def _reject(send: Send, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"www-authenticate", b"Bearer"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


def build_mcp_http(
    is_valid: Callable[[str], bool],
    settings: Settings | None = None,
    *,
    api_base_url: str | None = None,
) -> tuple[ASGIApp, Any]:
    """Return (ASGI app answering at MCP_PATH, lifespan context manager factory).
    The lifespan must be entered by the host application before requests arrive.

    Tools reach the REST API over loopback HTTP so they pass through exactly the
    same authorisation as any other API-key caller."""
    settings = settings or get_settings()
    client = KeyScopedClient(api_base_url or f"http://127.0.0.1:{settings.api_port}")
    server = build_server(
        client, wait_timeout=float(os.environ.get("ORGRAPH_MCP_WAIT_TIMEOUT", "60"))
    )
    inner = server.streamable_http_app(
        streamable_http_path=MCP_PATH,
        stateless_http=True,
        json_response=True,
        # Host/Origin allow-listing guards unauthenticated localhost servers
        # against DNS rebinding; every request here must carry an API key.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return BearerGate(inner, is_valid), lambda: inner.router.lifespan_context(inner)
