"""HTTP client for the Orgraph REST API (docs/api.md), authenticated with a
workspace API key. The MCP server only ever talks to the platform through this."""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings


class ApiError(Exception):
    """A request the API rejected or that never reached it. `status` is the
    HTTP status (0 when there was no response) and `detail` the API's message."""

    def __init__(self, status: int, detail: str) -> None:
        self.status, self.detail = status, detail
        super().__init__(f"Orgraph API error {status}: {detail}" if status else detail)


class MissingApiKey(ApiError):
    def __init__(self) -> None:
        super().__init__(
            0,
            "No Orgraph API key configured. Create one in the Orgraph UI under "
            "Settings → API keys and set it as ORGRAPH_API_KEY for this MCP server.",
        )


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return response.text.strip() or response.reason_phrase
    if isinstance(detail, list):  # FastAPI validation errors
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc", []) if p != "body")
                parts.append(f"{loc}: {item.get('msg')}" if loc else str(item.get("msg")))
            else:
                parts.append(str(item))
        return "; ".join(parts)
    return str(detail) if detail else response.reason_phrase


class ApiClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
    ) -> None:
        if base_url is None or api_key is None:
            settings = get_settings()
            base_url = base_url or settings.api_url
            api_key = api_key or settings.api_key
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._http = client or httpx.Client(transport=transport, timeout=timeout)
        self._workspace_id: str | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Call an absolute API path. Returns the decoded body (None for 204)."""
        if not self.api_key:
            raise MissingApiKey()
        if params:
            params = {k: v for k, v in params.items() if v is not None}
        try:
            response = self._http.request(
                method,
                self.base_url + path,
                json=json,
                params=params or None,
                headers={"X-API-Key": self.api_key},
            )
        except httpx.HTTPError as exc:
            raise ApiError(
                0, f"Cannot reach the Orgraph API at {self.base_url}: {exc or type(exc).__name__}"
            ) from exc
        if not response.is_success:
            raise ApiError(response.status_code, _detail(response))
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def me(self) -> dict[str, Any]:
        return self.request("GET", "/api/me")

    @property
    def workspace_id(self) -> str:
        """The API key's workspace, looked up once."""
        if self._workspace_id is None:
            workspaces = self.me().get("workspaces") or []
            if not workspaces:
                raise ApiError(0, "The API key is not attached to any workspace.")
            self._workspace_id = workspaces[0]["id"]
        return self._workspace_id

    def ws(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Call a path relative to the key's workspace, e.g. ws("GET", "/actions")."""
        return self.request(
            method, f"/api/workspaces/{self.workspace_id}{path}", json=json, params=params
        )

    def close(self) -> None:
        self._http.close()
