# Orgraph REST API

Base URL `http://127.0.0.1:8000`. All bodies are JSON. Timestamps are UTC ISO-8601 strings.

## Vocabulary

| Thing | Meaning |
|---|---|
| Connection | Credentials + config for one connector (`slack`, `github`, `jira`, `google`, `agent`) |
| Action | One reusable connector call: a connection, an operation and params |
| Operator | A workflow; each task runs one Action, in order |
| Schedule | Cron trigger for an Operator |
| Run | One execution of an Action or an Operator |
| Agent | Placeholder for a future AI agent, linked to actions and operators |

## Authentication

Send one of:

- `Authorization: Bearer <access_token>` — from signup/login, used by the UI.
- `X-API-Key: ogk_...` — a workspace API key, used by the MCP server. Acts as the user who
  created it, limited to that one workspace.

## MCP

`POST /mcp` is the MCP streamable-HTTP endpoint (stateless, JSON responses). It requires
`Authorization: Bearer ogk_...` with a workspace API key and answers 401 otherwise; login tokens are
not accepted. Its tools call this API as that key.

## Errors

Every error is `{"detail": "<message>"}` with a 4xx status (FastAPI validation errors keep their
standard 422 shape, where `detail` is a list).

| Status | When |
|---|---|
| 401 | Missing or invalid credentials |
| 403 | Not a member of the workspace, or owner role required |
| 404 | Resource does not exist in this workspace |
| 409 | Conflict (email taken, resource still in use) |
| 422 | Invalid body, cron, operation or params |

## Auth and identity

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/health` | | `{"status": "ok", "store": "falkor"}` |
| POST | `/api/auth/signup` | `{email, password, name, workspace_name?}` | 201 `{access_token, token_type: "bearer", user: User, workspace: Workspace}` |
| POST | `/api/auth/login` | `{email, password}` | `{access_token, token_type: "bearer", user: User}` |
| GET | `/api/me` | | `{user: User, workspaces: [Workspace]}` |

Signup creates a workspace (named `workspace_name`, default `"<name>'s workspace"`) owned by the new
user. Passwords are at least 8 characters. Emails are stored lowercased; a duplicate is 409. A wrong
email or password on login is 401.

```
User      {id, email, name, created_at}
Workspace {id, name, slug, role: "owner" | "member", created_at}
```

With an API key, `/api/me` lists only the key's workspace.

## Workspaces

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/workspaces` | | `[Workspace]` |
| POST | `/api/workspaces` | `{name}` | 201 `Workspace` (caller is owner) |
| GET | `/api/workspaces/{ws}/members` | | `[Member]` |
| POST | `/api/workspaces/{ws}/members` | `{email, role?}` | 201 `Member` — owner only; 404 if no user has that email |
| DELETE | `/api/workspaces/{ws}/members/{user_id}` | | 204 — owner only; 409 when removing the last owner |
| GET | `/api/workspaces/{ws}/api-keys` | | `[ApiKey]` |
| POST | `/api/workspaces/{ws}/api-keys` | `{name}` | 201 `ApiKey` plus `key` (full key, shown once) |
| DELETE | `/api/workspaces/{ws}/api-keys/{id}` | | 204 |
| GET | `/api/workspaces/{ws}/summary` | | `Summary` |

```
Member  {user_id, email, name, role}
ApiKey  {id, name, prefix, created_at, last_used_at}
Summary {counts: {connections, actions, operators, schedules, agents, runs},
         runs_by_status: {queued, running, succeeded, failed},
         recent_runs: [Run]   // newest 10
         graph: {<label>: count}}
```

Everything below is under `/api/workspaces/{ws}` and requires membership.

## Connector catalog

`GET /api/connectors` (any authenticated caller) returns `[ConnectorSpec]`:

```
ConnectorSpec {key, title, description, config_fields: [Field], operations: [Operation]}
Operation     {name, title, description, kind: "action" | "sync", params: [Field]}
Field         {name, label, type: "string"|"text"|"number"|"boolean"|"select",
               required, secret, help, default, options: [string], placeholder}
```

`config_fields` with `secret: true` go in a connection's `secrets`; the rest go in `config`.
`kind: "sync"` operations also write people, teams, projects, documents and tickets into the
workspace's company graph.

## Connections

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/connections` | | `[Connection]` |
| POST | `/connections` | `{name, connector, config?, secrets?}` | 201 `Connection` |
| GET | `/connections/{id}` | | `Connection` |
| PATCH | `/connections/{id}` | `{name?, config?, secrets?}` | `Connection` |
| DELETE | `/connections/{id}` | | 204; 409 if an action uses it |
| POST | `/connections/{id}/test` | | `{ok: bool, detail: string, identity: object}` |

```
Connection {id, name, connector, config, secret_fields: [string],
            status: "untested" | "ok" | "error", status_detail, created_at, updated_at}
```

Secrets are encrypted at rest and never returned; `secret_fields` lists which are set. On PATCH,
`secrets` is merged over the stored ones (send `null` for a field to clear it) and `config` replaces
the stored config. Unknown `connector` or a missing required field is 422. `test` calls the
external service, stores the outcome in `status`/`status_detail`, and always answers 200.

## Actions

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/actions` | | `[Action]` |
| POST | `/actions` | `{name, description?, connection_id, operation, params?}` | 201 `Action` |
| GET | `/actions/{id}` | | `Action` |
| PATCH | `/actions/{id}` | any of the create fields | `Action` |
| DELETE | `/actions/{id}` | | 204; 409 if an operator uses it |
| POST | `/actions/{id}/run` | `{input?}` | 202 `Run` |

```
Action {id, name, description, connection_id, connection_name, connector, operation,
        params, created_at, updated_at}
```

`operation` must exist on the connection's connector (422 otherwise).

### Templates

String values anywhere inside `params` may contain `{{ expression }}`:

- `{{ input.<path> }}` — the run's `input`
- `{{ tasks.<key>.output.<path> }}` — output of an earlier task (operators only)
- `{{ run.id }}`, `{{ run.started_at }}`

A value that is exactly one expression keeps the referenced value's type (list, number, object);
otherwise expressions are interpolated as text. Paths use dots, with integers indexing lists
(`tasks.find.output.issues.0.key`). An unresolvable expression fails the task.

## Operators

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/operators` | | `[Operator]` |
| POST | `/operators` | `{name, description?, tasks?, enabled?}` | 201 `Operator` |
| GET | `/operators/{id}` | | `Operator` |
| PATCH | `/operators/{id}` | any of the create fields | `Operator` |
| DELETE | `/operators/{id}` | | 204; also deletes its schedules |
| POST | `/operators/{id}/run` | `{input?}` | 202 `Run` |

```
Operator {id, name, description, enabled, tasks: [Task], created_at, updated_at}
Task     {key, action_id, params, continue_on_error}
```

Task keys are unique within the operator and match `[A-Za-z_][A-Za-z0-9_]*`; every `action_id` must
exist in the workspace (422 otherwise). A task's `params` are merged over its action's params.
Tasks run in order; a failed task fails the run and skips the rest unless it has
`continue_on_error`.

## Schedules

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/schedules` | `?operator_id=` | `[Schedule]` |
| POST | `/schedules` | `{operator_id, cron, timezone?, enabled?, input?}` | 201 `Schedule` |
| GET | `/schedules/{id}` | | `Schedule` |
| PATCH | `/schedules/{id}` | `{cron?, timezone?, enabled?, input?}` | `Schedule` |
| DELETE | `/schedules/{id}` | | 204 |

```
Schedule {id, operator_id, operator_name, cron, timezone, enabled, input,
          next_run_at, last_run_at, created_at, updated_at}
```

`cron` is a 5-field crontab expression evaluated in `timezone` (IANA name, default `UTC`); invalid
values are 422. `next_run_at` is recomputed whenever cron, timezone or enabled changes and is `null`
while disabled.

## Runs

| Method | Path | Query | Response |
|---|---|---|---|
| GET | `/runs` | `kind`, `target_id`, `status`, `limit` (default 50, max 200) | `[Run]`, newest first |
| GET | `/runs/{id}` | | `Run` |

```
Run        {id, kind: "action" | "operator", target_id, target_name,
            status: "queued" | "running" | "succeeded" | "failed",
            trigger: "manual" | "schedule" | "mcp" | "api", triggered_by,
            input, output, error, tasks: [TaskResult],
            created_at, started_at, finished_at}
TaskResult {key, action_id, action_name,
            status: "pending" | "running" | "succeeded" | "failed" | "skipped",
            output, error, started_at, finished_at}
```

An action run has one TaskResult with key `action`. A run's `output` is the action's output, or for
an operator `{<task key>: <task output>}`. `trigger` is `manual` for bearer-token callers and `mcp`
for API-key callers.

## Agents

Placeholders only: no agent runtime is attached and `status` is always `"not_connected"`.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/agents` | | `[Agent]` |
| POST | `/agents` | `{name, description?, provider?, model?, instructions?, action_ids?, operator_ids?}` | 201 `Agent` |
| GET | `/agents/{id}` | | `Agent` |
| PATCH | `/agents/{id}` | any of the create fields | `Agent` |
| DELETE | `/agents/{id}` | | 204 |

```
Agent {id, name, description, provider: "claude_code" | "openrouter" | "jev" | "custom",
       model, instructions, action_ids, operator_ids, status, created_at, updated_at}
```

Unknown action or operator ids are 422.

## Company graph

Each workspace has its own graph of people, teams, projects, documents, tickets and decisions.

| Method | Path | Body / query | Response |
|---|---|---|---|
| GET | `/graph/ontology` | | `{node_labels: {label: description}, edge_types: {type: description}}` |
| GET | `/graph/stats` | | `{nodes: {label: count}, total_nodes, total_edges}` |
| GET | `/graph/nodes` | `?label=&q=&limit=` (default 100, max 500) | `[GraphNode]` |
| POST | `/graph/nodes` | `{label, name, key?, props?}` | 201 `GraphNode` |
| GET | `/graph/nodes/{id}` | | `GraphNode` plus `edges: [GraphEdge]`, `neighbors: [GraphNode]` |
| PATCH | `/graph/nodes/{id}` | `{name?, props?}` | `GraphNode` |
| DELETE | `/graph/nodes/{id}` | | 204 |
| POST | `/graph/edges` | `{src, type, dst, props?}` | 201 `GraphEdge` |
| DELETE | `/graph/edges` | `?src=&type=&dst=` | 204 |
| GET | `/graph/subgraph` | `?label=&limit=` (default 200, max 1000) | `{nodes: [GraphNode], edges: [GraphEdge]}` |
| POST | `/graph/query` | `{cypher, params?}` | `{rows: [object]}` |

```
GraphNode {id, label, name, key, source, url, props, updated_at}
GraphEdge {src, type, dst, props}
```

`label` must be in the ontology's node labels and `type` in its edge types (422 otherwise). `q`
matches `name` case-insensitively. Manually created nodes get `source: "manual"` and, when `key` is
omitted, `key: "manual:<id>"`. `props` holds every property other than the named ones. `subgraph`
returns up to `limit` nodes and the edges between them. `query` runs read-only Cypher against the
workspace graph; it is 501 when the store backend is `memory`, and a Cypher error is 422.
