"""HTTP helpers shared by the built-in connectors."""

from __future__ import annotations

from typing import Any

import httpx

from .base import ConnectorContext, ConnectorError

MAX_ERROR_CHARS = 300


def error_text(resp: httpx.Response) -> str:
    """Best-effort extraction of the provider's error message from a response."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text.strip()[:MAX_ERROR_CHARS] or resp.reason_phrase
    if isinstance(body, dict):
        parts: list[str] = []
        for key in ("message", "error_description", "error", "errorMessages", "errors"):
            value = body.get(key)
            if isinstance(value, dict):
                value = value.get("message") or value
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            if value:
                parts.append(str(value))
        if parts:
            return "; ".join(dict.fromkeys(parts))[:MAX_ERROR_CHARS]
    return str(body)[:MAX_ERROR_CHARS]


def send(
    ctx: ConnectorContext, provider: str, method: str, url: str, **kwargs: Any
) -> httpx.Response:
    """Send a request, turning transport failures and 4xx/5xx into ConnectorError.
    Credentials travel in headers/auth only, so the message never contains them."""
    target = f"{method} {url.split('?', 1)[0]}"
    try:
        resp = ctx.http.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"{provider}: {target} failed: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        raise ConnectorError(
            f"{provider}: {target} returned {resp.status_code}: {error_text(resp)}"
        )
    return resp


def json_body(resp: httpx.Response, provider: str) -> Any:
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError as exc:
        raise ConnectorError(f"{provider}: response was not JSON") from exc


def require(source: dict[str, Any], name: str, provider: str, what: str = "connection") -> str:
    value = source.get(name)
    if value in (None, ""):
        raise ConnectorError(f"{provider}: {what} is missing {name!r}")
    return str(value).strip()


def as_int(value: Any, default: int, low: int = 1, high: int = 1000) -> int:
    """Coerce a param that may arrive as a string (from a form or a template)."""
    if value in (None, ""):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConnectorError(f"expected a number, got {value!r}") from exc
    return max(low, min(high, number))


def as_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def as_list(value: Any) -> list[str]:
    """Accept a list or a comma-separated string."""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(v) for v in value]
