import json

import httpx
import pytest

from anexa.mcp_server.client import ApiClient, ApiError, MissingApiKey

PREFIX = "/api/workspaces/ws1"


def body(request):
    return json.loads(request.content) if request.content else None


def test_sends_api_key_header_and_resolves_workspace_once(api, client):
    api.add("GET", f"{PREFIX}/actions", [{"id": "a1"}])

    assert client.ws("GET", "/actions") == [{"id": "a1"}]
    assert client.ws("GET", "/actions") == [{"id": "a1"}]

    assert len(api.calls("GET", "/api/me")) == 1
    assert all(r.headers["X-API-Key"] == "axk_test" for r in api.requests)
    assert str(api.last.url) == f"http://api.test{PREFIX}/actions"


def test_sends_json_body_and_drops_unset_query_params(api, client):
    api.add("POST", f"{PREFIX}/actions", {"id": "a1"}, status=201)
    api.add("GET", f"{PREFIX}/runs", [])

    client.ws("POST", "/actions", json={"name": "x"})
    assert body(api.last) == {"name": "x"}

    client.ws("GET", "/runs", params={"kind": "action", "status": None, "limit": 5})
    assert dict(api.last.url.params) == {"kind": "action", "limit": "5"}


def test_no_content_response_returns_none(api, client):
    api.add("DELETE", f"{PREFIX}/actions/a1", status=204)
    assert client.ws("DELETE", "/actions/a1") is None


def test_error_carries_status_and_detail(api, client):
    api.add("GET", f"{PREFIX}/actions/nope", {"detail": "Action not found"}, status=404)

    with pytest.raises(ApiError) as exc:
        client.ws("GET", "/actions/nope")

    assert exc.value.status == 404
    assert exc.value.detail == "Action not found"
    assert str(exc.value) == "Anexa API error 404: Action not found"


def test_validation_error_list_is_flattened(api, client):
    detail = [
        {"loc": ["body", "cron"], "msg": "Field required", "type": "missing"},
        {"loc": ["body", "tasks", 0, "key"], "msg": "bad key", "type": "value_error"},
    ]
    api.add("POST", f"{PREFIX}/schedules", {"detail": detail}, status=422)

    with pytest.raises(ApiError) as exc:
        client.ws("POST", "/schedules", json={})

    assert exc.value.status == 422
    assert exc.value.detail == "cron: Field required; tasks.0.key: bad key"


def test_non_json_error_body(client):
    transport = httpx.MockTransport(lambda r: httpx.Response(502, text="Bad Gateway"))
    client = ApiClient("http://api.test", "axk_test", transport=transport)

    with pytest.raises(ApiError) as exc:
        client.request("GET", "/api/me")

    assert (exc.value.status, exc.value.detail) == (502, "Bad Gateway")


def test_invalid_key_surfaces_401(api):
    api.routes[("GET", "/api/me")] = [(401, {"detail": "Invalid API key"})]
    client = ApiClient("http://api.test", "axk_bad", transport=httpx.MockTransport(api.handler))

    with pytest.raises(ApiError, match="401: Invalid API key"):
        client.ws("GET", "/actions")


def test_missing_api_key_explains_how_to_get_one(api, monkeypatch):
    monkeypatch.delenv("ANEXA_API_KEY", raising=False)
    client = ApiClient("http://api.test", "", transport=httpx.MockTransport(api.handler))

    with pytest.raises(MissingApiKey, match="Settings → API keys") as exc:
        client.ws("GET", "/actions")

    assert "ANEXA_API_KEY" in str(exc.value)
    assert api.requests == []


def test_unreachable_api_is_an_api_error():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    client = ApiClient("http://api.test", "axk_test", transport=httpx.MockTransport(refuse))

    with pytest.raises(ApiError, match="Cannot reach the Anexa API at http://api.test") as exc:
        client.me()

    assert exc.value.status == 0


def test_key_without_workspace(api):
    api.routes[("GET", "/api/me")] = [(200, {"user": {}, "workspaces": []})]
    client = ApiClient("http://api.test", "axk_test", transport=httpx.MockTransport(api.handler))

    with pytest.raises(ApiError, match="not attached to any workspace"):
        client.ws("GET", "/actions")


def test_defaults_come_from_settings(monkeypatch):
    from anexa.config import get_settings

    monkeypatch.setenv("ANEXA_API_URL", "http://anexa.internal:9000/")
    monkeypatch.setenv("ANEXA_API_KEY", "axk_env")
    get_settings.cache_clear()
    try:
        client = ApiClient()
        assert (client.base_url, client.api_key) == ("http://anexa.internal:9000", "axk_env")
    finally:
        get_settings.cache_clear()
