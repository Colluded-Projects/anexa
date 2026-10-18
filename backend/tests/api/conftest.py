from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import anexa.connectors as connectors
from anexa.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorSpec,
    FieldSpec,
    OperationResult,
    OperationSpec,
)
from anexa.engine import dispatch
from anexa.models import Run

GOOD_TOKEN = "xoxb-super-secret-token-value"


class FakeConnector(Connector):
    spec = ConnectorSpec(
        key="fake",
        title="Fake",
        description="Connector used by the API tests",
        config_fields=[
            FieldSpec(name="base_url", label="Base URL", required=True),
            FieldSpec(name="note", label="Note"),
            FieldSpec(name="token", label="Token", required=True, secret=True),
            FieldSpec(name="signing_secret", label="Signing secret", secret=True),
        ],
        operations=[
            OperationSpec(
                name="echo",
                title="Echo",
                params=[FieldSpec(name="text", label="Text", required=True)],
            ),
            OperationSpec(name="sync_all", title="Sync everything", kind="sync"),
        ],
    )

    def execute(self, operation, params, ctx):
        return OperationResult(output=dict(params))

    def test(self, ctx):
        if ctx.secrets.get("token") != GOOD_TOKEN:
            raise ConnectorError("token rejected")
        return {"user": "bot", "base_url": ctx.config.get("base_url")}


@pytest.fixture
def submitted(monkeypatch):
    """Replaces submit_run with one that records the call and queues a Run
    without touching Celery."""
    calls = []

    def fake_submit_run(
        repos, workspace_id, kind, target_id, *, trigger="manual", triggered_by=None, input=None
    ):
        repo = repos.actions if kind == "action" else repos.operators
        target = repo.get(target_id)
        if target is None or target.workspace_id != workspace_id:
            raise dispatch.TargetNotFound(f"{kind} {target_id!r} not found")
        run = repos.runs.create(
            Run(
                workspace_id=workspace_id,
                kind=kind,
                target_id=target_id,
                target_name=target.name,
                trigger=trigger,
                triggered_by=triggered_by,
                input=input or {},
            )
        )
        calls.append(run)
        return run

    monkeypatch.setattr(dispatch, "submit_run", fake_submit_run)
    return calls


@pytest.fixture
def client(store, settings, submitted, monkeypatch):
    monkeypatch.setattr(connectors, "_registry", {})
    monkeypatch.setattr(connectors, "_loaded", True)
    connectors.register(FakeConnector())
    from anexa.api.main import create_app

    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def signup(client):
    """signup("a@example.com") -> namespace(headers, user, ws, base, token)."""

    def _signup(email="ada@example.com", name="Ada", password="correct horse", **extra):
        r = client.post(
            "/api/auth/signup",
            json={"email": email, "password": password, "name": name, **extra},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        ws = body["workspace"]["id"]
        return SimpleNamespace(
            headers={"Authorization": f"Bearer {body['access_token']}"},
            token=body["access_token"],
            user=body["user"],
            ws=ws,
            base=f"/api/workspaces/{ws}",
            body=body,
        )

    return _signup


@pytest.fixture
def ada(signup):
    return signup()


@pytest.fixture
def bob(signup):
    return signup("bob@example.com", "Bob")


@pytest.fixture
def make(client):
    """Factories for the resources most tests need as setup."""

    def connection(who, **over):
        body = {
            "name": "Eng Fake",
            "connector": "fake",
            "config": {"base_url": "https://fake.example.com"},
            "secrets": {"token": GOOD_TOKEN},
            **over,
        }
        r = client.post(f"{who.base}/connections", json=body, headers=who.headers)
        assert r.status_code == 201, r.text
        return r.json()

    def action(who, connection_id=None, **over):
        connection_id = connection_id or connection(who)["id"]
        body = {
            "name": "Say hi",
            "connection_id": connection_id,
            "operation": "echo",
            "params": {"text": "hi {{ input.who }}"},
            **over,
        }
        r = client.post(f"{who.base}/actions", json=body, headers=who.headers)
        assert r.status_code == 201, r.text
        return r.json()

    def operator(who, action_id=None, **over):
        action_id = action_id or action(who)["id"]
        body = {
            "name": "Daily hello",
            "tasks": [{"key": "greet", "action_id": action_id}],
            **over,
        }
        r = client.post(f"{who.base}/operators", json=body, headers=who.headers)
        assert r.status_code == 201, r.text
        return r.json()

    def schedule(who, operator_id=None, **over):
        operator_id = operator_id or operator(who)["id"]
        body = {"operator_id": operator_id, "cron": "0 9 * * 1", **over}
        r = client.post(f"{who.base}/schedules", json=body, headers=who.headers)
        assert r.status_code == 201, r.text
        return r.json()

    def agent(who, **over):
        r = client.post(f"{who.base}/agents", json={"name": "Helper", **over}, headers=who.headers)
        assert r.status_code == 201, r.text
        return r.json()

    def node(who, label="Person", name="Grace", **over):
        r = client.post(
            f"{who.base}/graph/nodes",
            json={"label": label, "name": name, **over},
            headers=who.headers,
        )
        assert r.status_code == 201, r.text
        return r.json()

    def api_key(who, name="mcp"):
        r = client.post(f"{who.base}/api-keys", json={"name": name}, headers=who.headers)
        assert r.status_code == 201, r.text
        return r.json()

    return SimpleNamespace(
        connection=connection,
        action=action,
        operator=operator,
        schedule=schedule,
        agent=agent,
        node=node,
        api_key=api_key,
    )


@pytest.fixture
def token():
    """The secret the fake connector accepts; must never appear in a response."""
    return GOOD_TOKEN
