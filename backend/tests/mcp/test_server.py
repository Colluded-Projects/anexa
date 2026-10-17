import asyncio
import json

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from orgraph.mcp_server.client import ApiClient
from orgraph.mcp_server.server import build_server

PREFIX = "/api/workspaces/ws1"


def body(request):
    return json.loads(request.content) if request.content else None

EXPECTED_TOOLS = {
    "whoami",
    "list_connectors",
    "list_connections",
    "create_connection",
    "test_connection",
    "delete_connection",
    "list_actions",
    "get_action",
    "create_action",
    "update_action",
    "delete_action",
    "run_action",
    "list_operators",
    "get_operator",
    "create_operator",
    "update_operator",
    "delete_operator",
    "run_operator",
    "list_schedules",
    "create_schedule",
    "update_schedule",
    "delete_schedule",
    "list_runs",
    "get_run",
    "list_agents",
    "create_agent",
    "graph_ontology",
    "graph_stats",
    "graph_search",
    "graph_get_node",
    "graph_add_node",
    "graph_add_edge",
    "graph_query",
}


def test_registered_tools(server):
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    assert all(t.description and t.description.strip() for t in tools)


def test_workflow_tools_document_the_model_and_templates(server):
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    for name in ("create_action", "create_operator"):
        doc = tools[name].description
        assert "Connection" in doc and "Operator" in doc and "Schedule" in doc
        assert "{{ input.x }}" in doc and "{{ tasks.<key>.output.x }}" in doc
    assert tools["run_action"].input_schema["required"] == ["action_id"]
    assert set(tools["create_operator"].input_schema["required"]) == {"name", "tasks"}


# --- tools that read: (tool, arguments, path, query, response, expected result) ---

LIST = [{"id": "x1"}, {"id": "x2"}]
LISTED = {"count": 2, "items": LIST}

READS = [
    ("list_connectors", {}, "/api/connectors", {}, LIST, LISTED),
    ("list_connections", {}, f"{PREFIX}/connections", {}, LIST, LISTED),
    ("list_actions", {}, f"{PREFIX}/actions", {}, LIST, LISTED),
    ("get_action", {"action_id": "a1"}, f"{PREFIX}/actions/a1", {}, {"id": "a1"}, {"id": "a1"}),
    ("list_operators", {}, f"{PREFIX}/operators", {}, LIST, LISTED),
    ("get_operator", {"operator_id": "o1"}, f"{PREFIX}/operators/o1", {}, {"id": "o1"},
     {"id": "o1"}),
    ("list_schedules", {}, f"{PREFIX}/schedules", {}, LIST, LISTED),
    ("list_schedules", {"operator_id": "o1"}, f"{PREFIX}/schedules", {"operator_id": "o1"},
     LIST, LISTED),
    ("list_runs", {}, f"{PREFIX}/runs", {"limit": "20"}, LIST, LISTED),
    ("list_runs", {"kind": "operator", "target_id": "o1", "status": "failed", "limit": 5},
     f"{PREFIX}/runs",
     {"kind": "operator", "target_id": "o1", "status": "failed", "limit": "5"}, LIST, LISTED),
    ("get_run", {"run_id": "r1"}, f"{PREFIX}/runs/r1", {}, {"id": "r1"}, {"id": "r1"}),
    ("list_agents", {}, f"{PREFIX}/agents", {}, [], {"count": 0, "items": []}),
    ("graph_ontology", {}, f"{PREFIX}/graph/ontology", {},
     {"node_labels": {"Person": "p"}, "edge_types": {}},
     {"node_labels": {"Person": "p"}, "edge_types": {}}),
    ("graph_stats", {}, f"{PREFIX}/graph/stats", {},
     {"nodes": {"Person": 2}, "total_nodes": 2, "total_edges": 1},
     {"nodes": {"Person": 2}, "total_nodes": 2, "total_edges": 1}),
    ("graph_search", {}, f"{PREFIX}/graph/nodes", {"limit": "25"}, LIST, LISTED),
    ("graph_search", {"q": "alf", "label": "Person", "limit": 3}, f"{PREFIX}/graph/nodes",
     {"q": "alf", "label": "Person", "limit": "3"}, LIST, LISTED),
    ("graph_get_node", {"node_id": "n1"}, f"{PREFIX}/graph/nodes/n1", {},
     {"id": "n1", "edges": [], "neighbors": []}, {"id": "n1", "edges": [], "neighbors": []}),
]


@pytest.mark.parametrize("tool,args,path,query,response,expected", READS)
def test_read_tools(api, call, tool, args, path, query, response, expected):
    api.add("GET", path, response)

    assert call(tool, **args) == expected

    assert (api.last.method, api.last.url.path) == ("GET", path)
    assert dict(api.last.url.params) == query
    assert api.last.headers["X-API-Key"] == "ogk_test"


def test_whoami(api, call):
    result = call("whoami")

    assert result["user"]["email"] == "bruce@wayne.com"
    assert result["workspaces"][0]["id"] == "ws1"
    assert (result["workspace_id"], result["api_url"]) == ("ws1", "http://api.test")


# --- tools that write: (tool, arguments, method, path, expected request body) ---

TASKS = [
    {"key": "find", "action_id": "a1"},
    {"key": "post", "action_id": "a2", "params": {"text": "{{ tasks.find.output.total }}"}},
]

WRITES = [
    ("create_connection",
     {"name": "Eng Slack", "connector": "slack", "secrets": {"bot_token": "xoxb"}},
     "POST", f"{PREFIX}/connections",
     {"name": "Eng Slack", "connector": "slack", "secrets": {"bot_token": "xoxb"}}),
    ("create_connection",
     {"name": "Jira", "connector": "jira", "config": {"base_url": "https://x"}, "secrets": {}},
     "POST", f"{PREFIX}/connections",
     {"name": "Jira", "connector": "jira", "config": {"base_url": "https://x"}, "secrets": {}}),
    ("test_connection", {"connection_id": "c1"}, "POST", f"{PREFIX}/connections/c1/test", None),
    ("create_action",
     {"name": "Post", "connection_id": "c1", "operation": "post_message",
      "params": {"channel": "#eng", "text": "{{ input.text }}"}},
     "POST", f"{PREFIX}/actions",
     {"name": "Post", "description": "", "connection_id": "c1", "operation": "post_message",
      "params": {"channel": "#eng", "text": "{{ input.text }}"}}),
    ("create_action", {"name": "Sync", "connection_id": "c1", "operation": "sync_users"},
     "POST", f"{PREFIX}/actions",
     {"name": "Sync", "description": "", "connection_id": "c1", "operation": "sync_users",
      "params": {}}),
    ("update_action", {"action_id": "a1", "name": "Renamed"},
     "PATCH", f"{PREFIX}/actions/a1", {"name": "Renamed"}),
    ("update_action", {"action_id": "a1", "params": {}, "description": ""},
     "PATCH", f"{PREFIX}/actions/a1", {"params": {}, "description": ""}),
    ("create_operator", {"name": "Digest", "tasks": TASKS},
     "POST", f"{PREFIX}/operators",
     {"name": "Digest", "description": "", "tasks": TASKS, "enabled": True}),
    ("update_operator", {"operator_id": "o1", "enabled": False},
     "PATCH", f"{PREFIX}/operators/o1", {"enabled": False}),
    ("update_operator", {"operator_id": "o1", "tasks": []},
     "PATCH", f"{PREFIX}/operators/o1", {"tasks": []}),
    ("create_schedule", {"operator_id": "o1", "cron": "0 9 * * MON"},
     "POST", f"{PREFIX}/schedules",
     {"operator_id": "o1", "cron": "0 9 * * MON", "timezone": "UTC", "enabled": True,
      "input": {}}),
    ("create_schedule",
     {"operator_id": "o1", "cron": "*/5 * * * *", "timezone": "Europe/Berlin",
      "enabled": False, "input": {"team": "eng"}},
     "POST", f"{PREFIX}/schedules",
     {"operator_id": "o1", "cron": "*/5 * * * *", "timezone": "Europe/Berlin",
      "enabled": False, "input": {"team": "eng"}}),
    ("update_schedule", {"schedule_id": "s1", "enabled": False},
     "PATCH", f"{PREFIX}/schedules/s1", {"enabled": False}),
    ("update_schedule", {"schedule_id": "s1", "cron": "0 8 * * *", "timezone": "Asia/Kolkata"},
     "PATCH", f"{PREFIX}/schedules/s1", {"cron": "0 8 * * *", "timezone": "Asia/Kolkata"}),
    ("create_agent", {"name": "Alfred"}, "POST", f"{PREFIX}/agents",
     {"name": "Alfred", "description": "", "provider": "claude_code", "model": "",
      "instructions": "", "action_ids": [], "operator_ids": []}),
    ("create_agent",
     {"name": "Oracle", "provider": "jev", "model": "jev-1", "action_ids": ["a1"],
      "operator_ids": ["o1"], "instructions": "decide"},
     "POST", f"{PREFIX}/agents",
     {"name": "Oracle", "description": "", "provider": "jev", "model": "jev-1",
      "instructions": "decide", "action_ids": ["a1"], "operator_ids": ["o1"]}),
    ("graph_add_node", {"label": "Decision", "name": "Adopt FalkorDB"},
     "POST", f"{PREFIX}/graph/nodes", {"label": "Decision", "name": "Adopt FalkorDB"}),
    ("graph_add_node",
     {"label": "Team", "name": "Platform", "key": "team:platform", "props": {"size": 4}},
     "POST", f"{PREFIX}/graph/nodes",
     {"label": "Team", "name": "Platform", "key": "team:platform", "props": {"size": 4}}),
    ("graph_add_edge", {"src": "n1", "type": "MEMBER_OF", "dst": "n2"},
     "POST", f"{PREFIX}/graph/edges", {"src": "n1", "type": "MEMBER_OF", "dst": "n2"}),
    ("graph_add_edge", {"src": "n1", "type": "OWNS", "dst": "n2", "props": {"since": 2024}},
     "POST", f"{PREFIX}/graph/edges",
     {"src": "n1", "type": "OWNS", "dst": "n2", "props": {"since": 2024}}),
    ("graph_query", {"cypher": "MATCH (n) RETURN n.name"},
     "POST", f"{PREFIX}/graph/query", {"cypher": "MATCH (n) RETURN n.name", "params": {}}),
    ("graph_query", {"cypher": "MATCH (n {name: $n}) RETURN n", "params": {"n": "x"}},
     "POST", f"{PREFIX}/graph/query",
     {"cypher": "MATCH (n {name: $n}) RETURN n", "params": {"n": "x"}}),
]


@pytest.mark.parametrize("tool,args,method,path,expected_body", WRITES)
def test_write_tools(api, call, tool, args, method, path, expected_body):
    response = {"id": "new", "ok": True}
    api.add(method, path, response, status=201 if method == "POST" else 200)

    assert call(tool, **args) == response

    assert (api.last.method, api.last.url.path) == (method, path)
    assert body(api.last) == expected_body


DELETES = [
    ("delete_connection", "connection_id", "/connections/x1"),
    ("delete_action", "action_id", "/actions/x1"),
    ("delete_operator", "operator_id", "/operators/x1"),
    ("delete_schedule", "schedule_id", "/schedules/x1"),
]


@pytest.mark.parametrize("tool,arg,path", DELETES)
def test_delete_tools(api, call, tool, arg, path):
    api.add("DELETE", PREFIX + path, status=204)

    assert call(tool, **{arg: "x1"}) == {"deleted": True, "id": "x1"}
    assert (api.last.method, api.last.url.path) == ("DELETE", PREFIX + path)


# --- running ---------------------------------------------------------------------

RUNS = [
    ("run_action", "action_id", "/actions/t1/run"),
    ("run_operator", "operator_id", "/operators/t1/run"),
]


def run(status, **extra):
    return {"id": "r1", "status": status, "output": None, "error": None, **extra}


@pytest.mark.parametrize("tool,arg,path", RUNS)
def test_run_returns_immediately_when_already_finished(api, call, clock, tool, arg, path):
    # Celery in eager mode: the POST already answers with the finished run.
    api.add("POST", PREFIX + path, run("succeeded", output={"ok": True}), status=202)

    result = call(tool, **{arg: "t1"}, input={"text": "hi"})

    assert result == run("succeeded", output={"ok": True})
    assert body(api.last) == {"input": {"text": "hi"}}
    assert clock.sleeps == []
    assert api.calls("GET", f"{PREFIX}/runs/r1") == []


@pytest.mark.parametrize("tool,arg,path", RUNS)
def test_run_waits_until_terminal(api, call, clock, tool, arg, path):
    api.add("POST", PREFIX + path, run("queued"), status=202)
    api.add("GET", f"{PREFIX}/runs/r1", run("running"))
    api.add("GET", f"{PREFIX}/runs/r1", run("failed", error="channel_not_found"))

    result = call(tool, **{arg: "t1"})

    assert result == run("failed", error="channel_not_found")
    assert body(api.calls("POST", PREFIX + path)[0]) == {"input": {}}
    assert clock.sleeps == [2, 2]
    assert len(api.calls("GET", f"{PREFIX}/runs/r1")) == 2


@pytest.mark.parametrize("tool,arg,path", RUNS)
def test_run_without_wait_does_not_poll(api, call, clock, tool, arg, path):
    api.add("POST", PREFIX + path, run("queued"), status=202)

    assert call(tool, **{arg: "t1"}, wait=False) == run("queued")
    assert clock.sleeps == []
    assert api.calls("GET", f"{PREFIX}/runs/r1") == []


@pytest.mark.parametrize("tool,arg,path", RUNS)
def test_run_timeout_returns_running_run_with_note(api, call, clock, tool, arg, path):
    api.add("POST", PREFIX + path, run("queued"), status=202)
    api.add("GET", f"{PREFIX}/runs/r1", run("running"))

    result = call(tool, **{arg: "t1"})

    assert result["status"] == "running"
    assert result["id"] == "r1"
    assert "60s" in result["note"] and "get_run" in result["note"] and "r1" in result["note"]
    assert clock.now == 60
    assert len(clock.sleeps) == 30


def test_run_timeout_can_be_set_per_call(api, call, clock):
    api.add("POST", f"{PREFIX}/actions/t1/run", run("queued"), status=202)
    api.add("GET", f"{PREFIX}/runs/r1", run("running"))

    result = call("run_action", action_id="t1", timeout_seconds=4)

    assert "4s" in result["note"]
    assert clock.sleeps == [2, 2]


def test_default_wait_timeout_is_configurable(api, client, clock):
    api.add("POST", f"{PREFIX}/operators/t1/run", run("queued"), status=202)
    api.add("GET", f"{PREFIX}/runs/r1", run("queued"))
    server = build_server(
        client, wait_timeout=3, poll_interval=1, sleep=clock.sleep, clock=clock
    )

    asyncio.run(server.call_tool("run_operator", {"operator_id": "t1"}))

    assert clock.sleeps == [1, 1, 1]


# --- failures --------------------------------------------------------------------


def error_text(server, name, arguments):
    """What the model reads when a tool fails: the anticipated-error message."""
    with pytest.raises(ToolError) as exc:
        asyncio.run(server.call_tool(name, arguments))
    assert not isinstance(exc.value, UnexpectedToolError)
    return str(exc.value)


def test_api_error_is_reported_as_status_and_detail(api, server):
    api.add("GET", f"{PREFIX}/actions/nope", {"detail": "Action not found"}, status=404)

    text = error_text(server, "get_action", {"action_id": "nope"})

    assert "Orgraph API error 404: Action not found" in text
    assert "Traceback" not in text


def test_conflict_on_delete_is_reported(api, server):
    api.add(
        "DELETE", f"{PREFIX}/connections/c1", {"detail": "Connection is used by 2 actions"}, 409
    )

    text = error_text(server, "delete_connection", {"connection_id": "c1"})

    assert "409: Connection is used by 2 actions" in text


def test_failed_run_start_is_reported(api, server):
    api.add("POST", f"{PREFIX}/operators/o9/run", {"detail": "Operator not found"}, status=404)

    assert "404: Operator not found" in error_text(server, "run_operator", {"operator_id": "o9"})


def test_missing_api_key_is_reported(api):
    client = ApiClient("http://api.test", "", transport=httpx.MockTransport(api.handler))
    server = build_server(client)

    text = error_text(server, "list_actions", {})

    assert "Settings → API keys" in text
    assert api.requests == []


def test_missing_required_argument_is_rejected_before_any_request(api, server):
    text = error_text(server, "create_action", {"name": "x"})

    assert "connection_id" in text
    assert api.requests == []
