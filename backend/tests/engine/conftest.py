"""Shared fixtures for engine and worker tests: a fake connector plus small
factories for connections, actions and operators in one workspace."""

from typing import Any

import pytest

import anexa.connectors as connectors
from anexa.connectors import (
    Connector,
    ConnectorContext,
    ConnectorError,
    ConnectorSpec,
    EdgeUpsert,
    FieldSpec,
    GraphDelta,
    NodeUpsert,
    OperationResult,
    OperationSpec,
)
from anexa.models import Action, Connection, Operator, OperatorTask
from anexa.security import encrypt_secrets

WS = "ws1"


class FakeConnector(Connector):
    spec = ConnectorSpec(
        key="fake",
        title="Fake",
        config_fields=[FieldSpec(name="token", label="Token", secret=True)],
        operations=[
            OperationSpec(name="echo", title="Echo"),
            OperationSpec(name="fail", title="Fail"),
            OperationSpec(name="boom", title="Boom"),
            OperationSpec(name="bad_output", title="Bad output"),
            OperationSpec(
                name="needs", title="Needs", params=[FieldSpec(name="x", label="X", required=True)]
            ),
            OperationSpec(name="sync", title="Sync", kind="sync"),
        ],
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], ConnectorContext]] = []

    def execute(
        self, operation: str, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        self.calls.append((operation, params, ctx))
        if operation == "fail":
            raise ConnectorError("upstream said no")
        if operation == "boom":
            raise RuntimeError("kaboom")
        if operation == "bad_output":
            return OperationResult(output={"when": object()})
        if operation == "sync":
            return OperationResult(
                output={"synced": 2},
                graph=GraphDelta(
                    nodes=[
                        NodeUpsert(label="Person", key="email:a@x.io", props={"name": "Ada"}),
                        NodeUpsert(label="Team", key="fake:team:core", props={"name": "Core"}),
                    ],
                    edges=[
                        EdgeUpsert(
                            src_label="Person",
                            src_key="email:a@x.io",
                            type="MEMBER_OF",
                            dst_label="Team",
                            dst_key="fake:team:core",
                        )
                    ],
                ),
            )
        return OperationResult(output={"params": params, "secrets": ctx.secrets})

    def test(self, ctx: ConnectorContext) -> dict[str, Any]:
        return {"ok": True}


@pytest.fixture
def fake(monkeypatch):
    """Register a fake connector without loading the built-in ones."""
    monkeypatch.setattr(connectors, "_loaded", True)
    monkeypatch.setattr(connectors, "_registry", {})
    return connectors.register(FakeConnector())


@pytest.fixture
def ws():
    return WS


@pytest.fixture
def make_connection(repos, settings):
    def make(connector: str = "fake", workspace_id: str = WS, **kwargs: Any) -> Connection:
        kwargs.setdefault("secrets_enc", encrypt_secrets({"token": "s3cret"}, settings))
        return repos.connections.create(
            Connection(workspace_id=workspace_id, name="conn", connector=connector, **kwargs)
        )

    return make


@pytest.fixture
def make_action(repos, make_connection):
    def make(
        operation: str = "echo",
        params: dict[str, Any] | None = None,
        *,
        name: str | None = None,
        connection_id: str | None = None,
        workspace_id: str = WS,
    ) -> Action:
        connection_id = connection_id or make_connection().id
        return repos.actions.create(
            Action(
                workspace_id=workspace_id,
                name=name or operation,
                connection_id=connection_id,
                operation=operation,
                params=params or {},
            )
        )

    return make


@pytest.fixture
def make_operator(repos):
    def make(tasks: list[OperatorTask], **kwargs: Any) -> Operator:
        kwargs.setdefault("name", "op")
        return repos.operators.create(Operator(workspace_id=WS, tasks=tasks, **kwargs))

    return make
