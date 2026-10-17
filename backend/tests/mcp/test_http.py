"""MCP over HTTP at /mcp, exercised with the SDK's own client against a real
uvicorn server (tools call the API back over loopback, so it must be live)."""

import asyncio
import socket
import threading
import time

import httpx
import httpx2
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from orgraph.config import get_settings


@pytest.fixture
def live(store, monkeypatch):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setenv("ORGRAPH_API_PORT", str(port))
    get_settings.cache_clear()
    from orgraph.api.main import create_app

    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            httpx.get(base + "/api/health", timeout=1)
            break
        except httpx.HTTPError:
            time.sleep(0.05)
    yield base
    server.should_exit = True
    thread.join(timeout=5)
    get_settings.cache_clear()


def signup(base, email):
    body = httpx.post(
        base + "/api/auth/signup",
        json={"email": email, "password": "correct horse", "name": email.split("@")[0]},
    ).json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    ws = f"{base}/api/workspaces/{body['workspace']['id']}"
    key = httpx.post(ws + "/api-keys", json={"name": "claude"}, headers=headers).json()
    return ws, headers, key


def mcp_call(base, token, tool, arguments=None, *, list_tools=False):
    async def go():
        async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as http:
            async with streamable_http_client(base + "/mcp", http_client=http) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    if list_tools:
                        return [t.name for t in (await session.list_tools()).tools]
                    result = await session.call_tool(tool, arguments or {})
                    assert not result.is_error, result.content
                    return result.structured_content

    return asyncio.run(go())


def post_initialize(base, headers):
    return httpx.post(
        base + "/mcp",
        headers={"Accept": "application/json, text/event-stream", **headers},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
    )


def test_bearer_key_can_build_and_run_a_workflow_over_http(live):
    _, _, key = signup(live, "ada@acme.io")
    token = key["key"]

    assert "run_operator" in mcp_call(live, token, None, list_tools=True)
    conn = mcp_call(live, token, "create_connection", {"name": "Agent", "connector": "agent"})
    action = mcp_call(
        live,
        token,
        "create_action",
        {
            "name": "Ask",
            "connection_id": conn["id"],
            "operation": "invoke",
            "params": {"prompt": "hello {{ input.who }}"},
        },
    )
    operator = mcp_call(
        live,
        token,
        "create_operator",
        {"name": "Flow", "tasks": [{"key": "ask", "action_id": action["id"]}]},
    )
    run = mcp_call(
        live, token, "run_operator", {"operator_id": operator["id"], "input": {"who": "http"}}
    )

    assert run["status"] == "succeeded" and run["trigger"] == "mcp"
    assert run["tasks"][0]["output"]["prompt"] == "hello http"


def test_each_key_only_sees_its_own_workspace(live):
    _, _, ada = signup(live, "ada@acme.io")
    _, _, bob = signup(live, "bob@acme.io")
    mcp_call(live, ada["key"], "create_connection", {"name": "Ada's", "connector": "agent"})

    assert mcp_call(live, ada["key"], "list_connections")["count"] == 1
    assert mcp_call(live, bob["key"], "list_connections")["count"] == 0
    assert mcp_call(live, ada["key"], "whoami") != mcp_call(live, bob["key"], "whoami")


def test_requests_without_a_valid_key_are_rejected(live):
    ws, headers, key = signup(live, "ada@acme.io")

    assert post_initialize(live, {}).status_code == 401
    assert post_initialize(live, {"Authorization": "Bearer ogk_made-up"}).status_code == 401
    # A login token is not an API key: MCP access is always a revocable key.
    assert post_initialize(live, headers).status_code == 401
    good = {"Authorization": f"Bearer {key['key']}"}
    assert post_initialize(live, good).status_code == 200

    httpx.delete(f"{ws}/api-keys/{key['id']}", headers=headers)
    assert post_initialize(live, good).status_code == 401
