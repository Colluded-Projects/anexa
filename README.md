# Orgraph

An orchestration platform on top of a FalkorDB company graph. Connect Slack, GitHub, Jira and
Google, chain their operations into scheduled workflows, and build up one graph of the people,
teams, projects, documents, tickets and decisions in your company. Everything can be driven from the
web UI or from Claude Code over MCP.

No AI runs inside the platform yet. Agents can be defined and linked to actions and operators, but
they are empty shells with no runtime behind them.

## Branches

| Branch | Holds |
|---|---|
| `main` | Shared base: connectors store text (Slack messages, ticket bodies, doc content), a fake demo company with known-correct links, a precision/recall scorer, and the Graph → Linking tab. No linker yet. |
| `rules-only` | Linking without AI: email/name matching for people, regex for ticket keys and URLs, keyword overlap for related items, phrase rules for decisions, and "who knows what" experts. |
| `hybrid` | The same rules, then an LLM proposes extra links. Code checks every proposal before writing it. Unsure links go to a review queue. |

## Vocabulary

| Thing | Meaning |
|---|---|
| Connection | Credentials for one system (Slack, GitHub, Jira, Google, Agent), encrypted at rest |
| Action | One reusable call on a connection, e.g. `slack.post_message` |
| Operator | A workflow whose tasks run actions in order, passing outputs along with `{{ templates }}` |
| Schedule | A cron trigger for an operator |
| Run | One execution of an action or operator, with per-task status and output |
| Agent | Placeholder for a future AI agent, linked to actions and operators |

Actions whose operation is a *sync* (`github.sync_repos`, `slack.sync_users`, `jira.sync_issues`,
`google.sync_docs`, ...) also write what they find into the workspace's company graph.

## Run it with Docker

```
docker compose up --build
```

- UI: http://localhost:8080
- API: http://localhost:8000 (interactive docs at `/docs`)
- FalkorDB browser: http://localhost:3000

This starts FalkorDB (which is also the Celery broker), the API, a Celery worker, Celery beat and
the UI. Ports are bound to localhost. Before exposing it to anyone else, copy `.env.example` to
`.env` and set `ORGRAPH_SECRET_KEY`: it signs logins and encrypts stored credentials.

## Deploy on Render

`render.yaml` is a Blueprint: in Render choose **New > Blueprint** and select this repo. It creates
FalkorDB (private service with a persistent disk, also the Celery broker), the API (private
service), a Celery worker with beat embedded, and the public `web` service that serves the UI and
proxies `/api` and `/mcp` to the API. `ORGRAPH_SECRET_KEY` is generated for you; don't change it
after the first deploy. Private services and workers require paid instance types.

## Run it without Docker

Needs [uv](https://docs.astral.sh/uv/) and Node. Four terminals, all in `backend/` except the last:

```
uv sync
uv run orgraph-devdb        # embedded FalkorDB on localhost:6379, also the Celery broker
uv run orgraph-api          # http://127.0.0.1:8000
uv run celery -A orgraph.worker.celery_app worker --loglevel=info
uv run celery -A orgraph.worker.celery_app beat --loglevel=info

cd frontend && npm install && npm run dev    # http://localhost:5173
```

`orgraph-devdb` is for development; data lands in `backend/.orgraph/`. To use a FalkorDB server
instead, skip it and set `ORGRAPH_FALKORDB_HOST` / `ORGRAPH_FALKORDB_PORT` / `ORGRAPH_REDIS_URL`.
All settings are in `backend/src/orgraph/config.py` and read from `ORGRAPH_*` environment variables
or `backend/.env`.

## Claude Code (MCP)

The API serves MCP over HTTP at `/mcp`, authenticated with a workspace API key as a bearer token.

1. In the UI, open Settings → Connect Claude Code and click **Generate MCP config**. It creates an
   API key and shows a complete config with the key filled in (shown once).
2. Paste it into `.mcp.json` in your project, or into a Claude Code conversation:
   ```json
   {
     "mcpServers": {
       "orgraph": {
         "type": "http",
         "url": "http://localhost:8000/mcp",
         "headers": { "Authorization": "Bearer ogk_..." }
       }
     }
   }
   ```

Claude Code can then list connectors, create connections, actions, operators and schedules, start
runs and wait for their result (`run_action`, `run_operator`), and read or extend the company graph.
A key is bound to one workspace, acts as the user who created it, and can be revoked under
Settings → API keys. Login tokens are not accepted on `/mcp`.

The same tools are available over stdio (`uv run --directory backend orgraph-mcp`, with
`ORGRAPH_API_KEY` and `ORGRAPH_API_URL` set); the Settings panel shows that config too.

## Tests

```
cd backend
uv run pytest                               # in-memory store
ORGRAPH_TEST_FALKOR_LITE=1 uv run pytest    # same suite on an embedded FalkorDB engine

cd frontend
npm test && npm run build
```

`backend/tests/e2e` runs the whole path in one process: MCP tool → REST API → Celery (eager) →
executor → real connector code → company graph. External services are mocked in every test.

## Layout

```
backend/src/orgraph/
  store/        GraphStore contract, FalkorDB and in-memory implementations
  models.py     stored domain models        repos.py   typed persistence
  connectors/   slack, github, jira, google, agent (placeholder)
  engine/       templating, executor, dispatch
  worker/       Celery app, run task, scheduler tick
  graph/        company graph ontology and ingest
  api/          FastAPI app and routers
  mcp_server/   MCP server (a client of the REST API)
frontend/       React + Vite + TypeScript + Tailwind
docs/api.md     REST API reference
```
