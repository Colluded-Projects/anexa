"""Everything wired together for real: MCP tools -> REST API -> dispatch ->
Celery (eager) -> executor -> real connectors -> company graph. Only the
external HTTP services and the store backend (in-memory) are substituted."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from anexa.mcp_server.client import ApiClient
from anexa.mcp_server.server import build_server
from anexa.repos import Repos
from anexa.worker.tasks import run_scheduler_tick

GITHUB_TOKEN = "ghp_e2e-secret-token"
SLACK_TOKEN = "xoxb-e2e-secret-token"


@pytest.fixture
def api(store, settings):
    from anexa.api.main import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def external():
    """The outside world. Requests to the in-process API are not intercepted."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://api.github.com/user/repos").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "name": "api",
                        "full_name": "acme/api",
                        "html_url": "https://github.com/acme/api",
                        "description": "The API",
                        "private": False,
                        "owner": {"login": "acme"},
                    }
                ],
            )
        )
        mock.get("https://api.github.com/repos/acme/api/issues").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {
                        "number": 7,
                        "title": "Login is broken",
                        "state": "open",
                        "html_url": "https://github.com/acme/api/issues/7",
                        "user": {"login": "ada"},
                    }
                ],
            )
        )
        mock.post("https://slack.com/api/chat.postMessage").mock(
            return_value=httpx.Response(200, json={"ok": True, "ts": "1.2", "channel": "C1"})
        )
        yield mock


@pytest.fixture
def mcp(api):
    """An MCP server authenticated with an API key created through the UI's API."""
    signup = api.post(
        "/api/auth/signup",
        json={"email": "ada@acme.io", "password": "correct horse", "name": "Ada"},
    ).json()
    ws = signup["workspace"]["id"]
    bearer = {"Authorization": f"Bearer {signup['access_token']}"}
    key = api.post(f"/api/workspaces/{ws}/api-keys", json={"name": "claude"}, headers=bearer)
    assert key.status_code == 201, key.text

    server = build_server(
        ApiClient("http://testserver", key.json()["key"], client=api), sleep=lambda _: None
    )

    def call(name, /, **arguments):
        result = asyncio.run(server.call_tool(name, arguments))
        assert not result.is_error, result.content
        return result.structured_content

    call.ws, call.bearer = ws, bearer
    return call


def build_digest_operator(mcp):
    github = mcp(
        "create_connection", name="GitHub", connector="github", secrets={"token": GITHUB_TOKEN}
    )
    slack = mcp(
        "create_connection", name="Slack", connector="slack", secrets={"bot_token": SLACK_TOKEN}
    )
    sync = mcp(
        "create_action", name="Sync repos", connection_id=github["id"], operation="sync_repos"
    )
    find = mcp(
        "create_action",
        name="Find issues",
        connection_id=github["id"],
        operation="list_issues",
        params={"repo": "{{ input.repo }}"},
    )
    post = mcp(
        "create_action",
        name="Post to eng",
        connection_id=slack["id"],
        operation="post_message",
        params={"channel": "#eng", "text": "placeholder"},
    )
    operator = mcp(
        "create_operator",
        name="Issue digest",
        tasks=[
            {"key": "sync", "action_id": sync["id"]},
            {"key": "find", "action_id": find["id"]},
            {
                "key": "notify",
                "action_id": post["id"],
                "params": {
                    "text": "{{ tasks.find.output.count }} open in {{ input.repo }}: "
                    "{{ tasks.find.output.issues.0.title }}"
                },
            },
        ],
    )
    return operator


def test_claude_code_builds_and_runs_a_workflow(mcp, api, external, store):
    operator = build_digest_operator(mcp)

    run = mcp("run_operator", operator_id=operator["id"], input={"repo": "acme/api"})

    assert run["status"] == "succeeded", run
    assert run["trigger"] == "mcp"
    assert [t["status"] for t in run["tasks"]] == ["succeeded"] * 3

    # Credentials were decrypted and sent; templates were resolved across tasks.
    slack_request = external.calls[-1].request
    assert slack_request.headers["authorization"] == f"Bearer {SLACK_TOKEN}"
    assert json.loads(slack_request.content)["text"] == "1 open in acme/api: Login is broken"
    github_request = external.calls[0].request
    assert GITHUB_TOKEN in github_request.headers["authorization"]

    # The sync task wrote the repository into the workspace's company graph.
    found = mcp("graph_search", q="api", label="Project")
    assert [n["name"] for n in found["items"]] == ["acme/api"] or found["items"][0]["key"] == (
        "github:repo:acme/api"
    )

    # Secrets never come back out, through either the MCP tools or the REST API.
    everything = json.dumps(
        [
            mcp("list_connections"),
            mcp("list_runs"),
            api.get(f"/api/workspaces/{mcp.ws}/summary", headers=mcp.bearer).json(),
        ]
    )
    assert GITHUB_TOKEN not in everything and SLACK_TOKEN not in everything


def test_a_failing_external_call_fails_the_run_with_a_readable_error(mcp, external):
    operator = build_digest_operator(mcp)
    external.post("https://slack.com/api/chat.postMessage").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "channel_not_found"})
    )

    run = mcp("run_operator", operator_id=operator["id"], input={"repo": "acme/api"})

    assert run["status"] == "failed"
    assert [t["status"] for t in run["tasks"]] == ["succeeded", "succeeded", "failed"]
    assert "channel_not_found" in run["tasks"][2]["error"]
    assert SLACK_TOKEN not in json.dumps(run)


def test_a_schedule_created_over_mcp_is_fired_by_the_scheduler(mcp, external, store, settings):
    operator = build_digest_operator(mcp)
    schedule = mcp(
        "create_schedule", operator_id=operator["id"], cron="0 9 * * *", input={"repo": "acme/api"}
    )
    assert schedule["next_run_at"]

    repos = Repos(store, settings)
    assert run_scheduler_tick(repos, now=datetime.now(UTC) - timedelta(days=1))  # not due yet
    assert mcp("list_runs")["count"] == 0

    run_scheduler_tick(repos, now=datetime.now(UTC) + timedelta(days=1, minutes=1))

    runs = mcp("list_runs")["items"]
    assert len(runs) == 1
    assert runs[0]["trigger"] == "schedule" and runs[0]["status"] == "succeeded"
    assert runs[0]["triggered_by"] == schedule["id"]

    run_scheduler_tick(repos, now=datetime.now(UTC) + timedelta(days=1, minutes=2))
    assert mcp("list_runs")["count"] == 1  # same interval is not fired twice


def test_agent_is_an_unconnected_shell_linked_to_work(mcp):
    operator = build_digest_operator(mcp)
    agent = mcp("create_agent", name="Ops agent", provider="jev", operator_ids=[operator["id"]])

    assert agent["status"] == "not_connected"
    assert agent["operator_ids"] == [operator["id"]]

    conn = mcp("create_connection", name="Agent", connector="agent", config={"provider": "jev"})
    action = mcp(
        "create_action",
        name="Ask",
        connection_id=conn["id"],
        operation="invoke",
        params={"prompt": "hi"},
    )
    run = mcp("run_action", action_id=action["id"])
    assert run["status"] == "succeeded"
    assert run["output"]["status"] == "not_connected"


@pytest.mark.skipif(
    not os.environ.get("ANEXA_TEST_FALKOR_LITE"), reason="raw Cypher needs a FalkorDB engine"
)
def test_cypher_over_mcp_reads_the_synced_graph_and_cannot_write(mcp, external):
    operator = build_digest_operator(mcp)
    mcp("run_operator", operator_id=operator["id"], input={"repo": "acme/api"})

    rows = mcp("graph_query", cypher="MATCH (p:Project) RETURN p.name AS name, p.source AS source")
    assert rows["rows"] == [{"name": "acme/api", "source": "github"}]

    with pytest.raises(Exception, match="read-only"):
        mcp("graph_query", cypher="CREATE (:Person {name: 'intruder'})")
    assert mcp("graph_search", label="Person")["count"] == 0
