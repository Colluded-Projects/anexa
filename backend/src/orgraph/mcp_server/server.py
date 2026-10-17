"""MCP server for Claude Code. Every tool is a thin call to the REST API."""

from __future__ import annotations

import functools
import os
import time
from collections.abc import Callable
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import ApiClient, ApiError

INSTRUCTIONS = """\
Orgraph orchestrates work across a company's tools and keeps a graph of its \
people, teams, projects, documents, tickets and decisions.

Model: a Connection holds credentials for one connector (slack, github, jira, \
google, agent). An Action is one reusable connector call (connection + \
operation + params). An Operator is a workflow whose tasks each run one Action, \
in order. A Schedule runs an Operator on a cron. Every execution is a Run.

Typical flow: list_connectors (what operations exist and their params) -> \
list_connections -> create_action -> run_action to try it -> create_operator \
chaining actions -> run_operator -> create_schedule."""

TERMINAL = ("succeeded", "failed")

RunKind = Literal["action", "operator"]
RunStatus = Literal["queued", "running", "succeeded", "failed"]
AgentProvider = Literal["claude_code", "openrouter", "jev", "custom"]


def _items(rows: list[Any] | None) -> dict[str, Any]:
    rows = rows or []
    return {"count": len(rows), "items": rows}


def _set(**fields: Any) -> dict[str, Any]:
    """Body containing only the fields the caller actually supplied."""
    return {k: v for k, v in fields.items() if v is not None}


def build_server(
    client: ApiClient,
    *,
    wait_timeout: float = 60.0,
    poll_interval: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> MCPServer:
    mcp = MCPServer("orgraph", instructions=INSTRUCTIONS)

    def tool(fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register `fn` as a tool. API failures become ToolErrors so the model
        reads the status and detail instead of a generic crash message."""

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except ApiError as exc:
                raise ToolError(str(exc)) from exc

        return mcp.tool()(wrapper)

    def start_run(path: str, input: dict[str, Any] | None, wait: bool, timeout: float | None):
        run = client.ws("POST", path, json={"input": input or {}})
        if not wait:
            return run
        limit = wait_timeout if timeout is None else timeout
        deadline = clock() + limit
        while run["status"] not in TERMINAL:
            if clock() >= deadline:
                return {
                    **run,
                    "note": f"Still {run['status']} after {limit:g}s; "
                    f"call get_run with id {run['id']} to check again.",
                }
            sleep(poll_interval)
            run = client.ws("GET", f"/runs/{run['id']}")
        return run

    # --- identity and catalog ------------------------------------------------

    @tool
    def whoami() -> dict[str, Any]:
        """Show the user and workspace this server's API key acts as."""
        me = client.me()
        return {**me, "workspace_id": client.workspace_id, "api_url": client.base_url}

    @tool
    def list_connectors() -> dict[str, Any]:
        """List the connector catalog: every connector (slack, github, jira, google,
        agent), the config/secret fields a connection needs, and each operation with
        its params. Operations of kind "sync" also write people, teams, projects,
        documents and tickets into the company graph. Read this before create_action
        to pick a valid `operation` and its params."""
        return _items(client.request("GET", "/api/connectors"))

    # --- connections ---------------------------------------------------------

    @tool
    def list_connections() -> dict[str, Any]:
        """List the workspace's connections (credentials for one connector each).
        Secrets are never returned; `secret_fields` names the ones that are set."""
        return _items(client.ws("GET", "/connections"))

    @tool
    def create_connection(
        name: str,
        connector: str,
        config: dict[str, Any] | None = None,
        secrets: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a connection for a connector.

        connector: a key from list_connectors (slack, github, jira, google, agent).
        config: the connector's non-secret config_fields, e.g. {"base_url": "..."}.
        secrets: its secret config_fields (tokens); encrypted at rest, never returned.
        Run test_connection afterwards to verify the credentials."""
        body = {"name": name, "connector": connector, **_set(config=config, secrets=secrets)}
        return client.ws("POST", "/connections", json=body)

    @tool
    def test_connection(connection_id: str) -> dict[str, Any]:
        """Verify a connection's credentials against the external service.
        Returns {ok, detail, identity}; ok=false means the credentials did not work."""
        return client.ws("POST", f"/connections/{connection_id}/test")

    @tool
    def delete_connection(connection_id: str) -> dict[str, Any]:
        """Delete a connection. Fails with 409 while any action still uses it."""
        client.ws("DELETE", f"/connections/{connection_id}")
        return {"deleted": True, "id": connection_id}

    # --- actions -------------------------------------------------------------

    @tool
    def list_actions() -> dict[str, Any]:
        """List the workspace's actions (one reusable connector call each)."""
        return _items(client.ws("GET", "/actions"))

    @tool
    def get_action(action_id: str) -> dict[str, Any]:
        """Get one action, including its connection, operation and params."""
        return client.ws("GET", f"/actions/{action_id}")

    @tool
    def create_action(
        name: str,
        connection_id: str,
        operation: str,
        params: dict[str, Any] | None = None,
        description: str = "",
    ) -> dict[str, Any]:
        """Create an action: one reusable call to a connector.

        Model: Connection (credentials) -> Action (connection + operation + params)
        -> Operator (ordered tasks, each running one Action) -> Schedule (cron).

        connection_id: from list_connections.
        operation: an operation name of that connection's connector (list_connectors).
        params: the operation's params. String values may contain templates:
          {{ input.x }}                 a field of the run's input
          {{ tasks.<key>.output.x }}    output of an earlier operator task
          {{ run.id }}, {{ run.started_at }}
        A value that is exactly one expression keeps its type (list, number, object);
        otherwise expressions are interpolated as text. Paths use dots, integers
        index lists (tasks.find.output.issues.0.key).

        Example: create_action("Post to #eng", conn_id, "post_message",
                 {"channel": "#eng", "text": "{{ input.text }}"})"""
        body = {
            "name": name,
            "description": description,
            "connection_id": connection_id,
            "operation": operation,
            "params": params or {},
        }
        return client.ws("POST", "/actions", json=body)

    @tool
    def update_action(
        action_id: str,
        name: str | None = None,
        description: str | None = None,
        connection_id: str | None = None,
        operation: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Change an action. Only the fields you pass are updated; `params`
        replaces the stored params as a whole."""
        body = _set(
            name=name,
            description=description,
            connection_id=connection_id,
            operation=operation,
            params=params,
        )
        return client.ws("PATCH", f"/actions/{action_id}", json=body)

    @tool
    def delete_action(action_id: str) -> dict[str, Any]:
        """Delete an action. Fails with 409 while any operator still uses it."""
        client.ws("DELETE", f"/actions/{action_id}")
        return {"deleted": True, "id": action_id}

    @tool
    def run_action(
        action_id: str,
        input: dict[str, Any] | None = None,
        wait: bool = True,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run an action now and return its Run.

        input: values for the action's {{ input.x }} templates.
        wait: when true (default) poll until the run has succeeded or failed, or
        until timeout_seconds (default 60) passes; a run that is still going is
        returned as-is with a `note`. When false, return the queued run at once.
        Check `status`, `output` and `error` on the result."""
        return start_run(f"/actions/{action_id}/run", input, wait, timeout_seconds)

    # --- operators -----------------------------------------------------------

    @tool
    def list_operators() -> dict[str, Any]:
        """List the workspace's operators (workflows of actions)."""
        return _items(client.ws("GET", "/operators"))

    @tool
    def get_operator(operator_id: str) -> dict[str, Any]:
        """Get one operator with its ordered tasks."""
        return client.ws("GET", f"/operators/{operator_id}")

    @tool
    def create_operator(
        name: str,
        tasks: list[dict[str, Any]],
        description: str = "",
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create an operator: a workflow whose tasks each run one Action, in order.

        Model: Connection (credentials) -> Action (one connector call) -> Operator
        (this) -> Schedule (cron trigger, see create_schedule).

        tasks: ordered list of
          {"key": str, "action_id": str, "params": {...}, "continue_on_error": bool}
          key: unique within the operator, letters/digits/underscore, not starting
               with a digit. action_id: from list_actions. params (optional): merged
               over the action's own params. continue_on_error (optional, default
               false): without it a failed task fails the run and skips the rest.
        Templates in params pass data between tasks:
          {{ tasks.<key>.output.x }}    output of an earlier task
          {{ input.x }}                 the run's input
        Example:
          [{"key": "find", "action_id": "<search issues action>"},
           {"key": "post", "action_id": "<post message action>",
            "params": {"text": "Open bugs: {{ tasks.find.output.total }}"}}]"""
        body = {"name": name, "description": description, "tasks": tasks, "enabled": enabled}
        return client.ws("POST", "/operators", json=body)

    @tool
    def update_operator(
        operator_id: str,
        name: str | None = None,
        description: str | None = None,
        tasks: list[dict[str, Any]] | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        """Change an operator. Only the fields you pass are updated; `tasks`
        replaces the whole task list (same shape as in create_operator)."""
        body = _set(name=name, description=description, tasks=tasks, enabled=enabled)
        return client.ws("PATCH", f"/operators/{operator_id}", json=body)

    @tool
    def delete_operator(operator_id: str) -> dict[str, Any]:
        """Delete an operator together with its schedules."""
        client.ws("DELETE", f"/operators/{operator_id}")
        return {"deleted": True, "id": operator_id}

    @tool
    def run_operator(
        operator_id: str,
        input: dict[str, Any] | None = None,
        wait: bool = True,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        """Run an operator now and return its Run, with one entry per task in `tasks`.

        input: values for {{ input.x }} templates in the tasks' params.
        wait: when true (default) poll until the run has succeeded or failed, or
        until timeout_seconds (default 60) passes; a run that is still going is
        returned as-is with a `note`. When false, return the queued run at once.
        The run's `output` maps each task key to that task's output."""
        return start_run(f"/operators/{operator_id}/run", input, wait, timeout_seconds)

    # --- schedules -----------------------------------------------------------

    @tool
    def list_schedules(operator_id: str | None = None) -> dict[str, Any]:
        """List cron schedules, optionally only those of one operator."""
        return _items(client.ws("GET", "/schedules", params={"operator_id": operator_id}))

    @tool
    def create_schedule(
        operator_id: str,
        cron: str,
        timezone: str = "UTC",
        enabled: bool = True,
        input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run an operator on a cron schedule.

        cron: 5-field crontab expression, e.g. "0 9 * * MON" (Mondays 09:00).
        timezone: IANA name the cron is evaluated in, e.g. "Europe/Berlin".
        input: passed as the run's input on every scheduled run.
        The result's next_run_at shows when it fires next."""
        body = {
            "operator_id": operator_id,
            "cron": cron,
            "timezone": timezone,
            "enabled": enabled,
            "input": input or {},
        }
        return client.ws("POST", "/schedules", json=body)

    @tool
    def update_schedule(
        schedule_id: str,
        cron: str | None = None,
        timezone: str | None = None,
        enabled: bool | None = None,
        input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Change a schedule's cron, timezone or input, or pause/resume it with
        `enabled`. Only the fields you pass are updated."""
        body = _set(cron=cron, timezone=timezone, enabled=enabled, input=input)
        return client.ws("PATCH", f"/schedules/{schedule_id}", json=body)

    @tool
    def delete_schedule(schedule_id: str) -> dict[str, Any]:
        """Delete a schedule. The operator itself is kept."""
        client.ws("DELETE", f"/schedules/{schedule_id}")
        return {"deleted": True, "id": schedule_id}

    # --- runs ----------------------------------------------------------------

    @tool
    def list_runs(
        kind: RunKind | None = None,
        target_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List recent runs, newest first.

        kind: "action" or "operator". target_id: only runs of that action/operator.
        status: queued, running, succeeded or failed. limit: at most 200."""
        params = {"kind": kind, "target_id": target_id, "status": status, "limit": limit}
        return _items(client.ws("GET", "/runs", params=params))

    @tool
    def get_run(run_id: str) -> dict[str, Any]:
        """Get one run: status, input, output, error and per-task results."""
        return client.ws("GET", f"/runs/{run_id}")

    # --- agents --------------------------------------------------------------

    @tool
    def list_agents() -> dict[str, Any]:
        """List agent placeholders. No agent runtime is attached yet, so every
        agent has status "not_connected"."""
        return _items(client.ws("GET", "/agents"))

    @tool
    def create_agent(
        name: str,
        description: str = "",
        provider: AgentProvider = "claude_code",
        model: str = "",
        instructions: str = "",
        action_ids: list[str] | None = None,
        operator_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Register an agent placeholder and link the actions and operators it
        should be allowed to use. This only records the configuration; nothing
        runs the agent yet (status stays "not_connected")."""
        body = {
            "name": name,
            "description": description,
            "provider": provider,
            "model": model,
            "instructions": instructions,
            "action_ids": action_ids or [],
            "operator_ids": operator_ids or [],
        }
        return client.ws("POST", "/agents", json=body)

    # --- company graph -------------------------------------------------------

    @tool
    def graph_ontology() -> dict[str, Any]:
        """List the node labels and edge types the company graph accepts, with
        what each means. Read this before graph_add_node / graph_add_edge."""
        return client.ws("GET", "/graph/ontology")

    @tool
    def graph_stats() -> dict[str, Any]:
        """Count the company graph's nodes per label and its edges."""
        return client.ws("GET", "/graph/stats")

    @tool
    def graph_search(
        q: str | None = None, label: str | None = None, limit: int = 25
    ) -> dict[str, Any]:
        """Find nodes in the company graph.

        q: case-insensitive match on the node's name. label: Person, Team,
        Project, Document, Ticket or Decision. limit: at most 500."""
        params = {"q": q, "label": label, "limit": limit}
        return _items(client.ws("GET", "/graph/nodes", params=params))

    @tool
    def graph_get_node(node_id: str) -> dict[str, Any]:
        """Get a node with its `edges` and `neighbors`: who and what it is
        connected to. Use ids from graph_search."""
        return client.ws("GET", f"/graph/nodes/{node_id}")

    @tool
    def graph_add_node(
        label: str,
        name: str,
        key: str | None = None,
        props: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a node to the company graph, e.g. a Decision or a Team.

        label: one of graph_ontology's node labels. key: optional stable identity
        within the label (defaults to "manual:<id>"). props: any further
        properties, e.g. {"rationale": "...", "url": "..."}."""
        body = {"label": label, "name": name, **_set(key=key, props=props)}
        return client.ws("POST", "/graph/nodes", json=body)

    @tool
    def graph_add_edge(
        src: str, type: str, dst: str, props: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Connect two nodes: (src)-[type]->(dst).

        src, dst: node ids. type: one of graph_ontology's edge types, e.g.
        MEMBER_OF (Person -> Team), DECIDED (Person -> Decision), AFFECTS
        (Decision -> Project). Adding an existing edge updates its props."""
        body = {"src": src, "type": type, "dst": dst, **_set(props=props)}
        return client.ws("POST", "/graph/edges", json=body)

    @tool
    def graph_query(cypher: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run read-only Cypher against the workspace's company graph (FalkorDB)
        and return {rows}. Nodes carry key, name, source and url properties.

        Example: MATCH (p:Person)-[:MEMBER_OF]->(t:Team {name: $team})
                 RETURN p.name, p.key   with params {"team": "Platform"}"""
        return client.ws("POST", "/graph/query", json={"cypher": cypher, "params": params or {}})

    return mcp


def main() -> None:
    """Entry point for `orgraph-mcp` (stdio transport)."""
    timeout = float(os.environ.get("ORGRAPH_MCP_WAIT_TIMEOUT", "60"))
    build_server(ApiClient(), wait_timeout=timeout).run()


if __name__ == "__main__":
    main()
