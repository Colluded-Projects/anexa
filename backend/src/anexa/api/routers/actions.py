from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from ...models import Action, Connection
from ..common import invalid, scoped, start_run
from ..deps import WorkspaceCtx, WorkspaceDep
from ..schemas import ActionIn, ActionOut, ActionPatch, RunIn, RunOut
from .connections import connector_or_422

router = APIRouter(prefix="/api/workspaces/{ws}/actions", tags=["actions"])


def _connection(ctx: WorkspaceCtx, connection_id: str) -> Connection:
    conn = ctx.repos.connections.get(connection_id)
    if conn is None or conn.workspace_id != ctx.id:
        raise invalid(f"connection {connection_id!r} does not exist in this workspace")
    return conn


def _check_operation(conn: Connection, operation: str) -> None:
    spec = connector_or_422(conn.connector).spec
    if spec.operation(operation) is None:
        known = ", ".join(op.name for op in spec.operations)
        raise invalid(f"{spec.key} has no operation {operation!r} (available: {known})")


def _out(action: Action, connections: dict[str, Connection]) -> ActionOut:
    conn = connections.get(action.connection_id)
    return ActionOut(
        **action.model_dump(exclude={"workspace_id"}),
        connection_name=conn.name if conn else "",
        connector=conn.connector if conn else "",
    )


def _one(ctx: WorkspaceCtx, action: Action) -> ActionOut:
    conn = ctx.repos.connections.get(action.connection_id)
    return _out(action, {conn.id: conn} if conn else {})


@router.get("")
def list_actions(ctx: WorkspaceDep) -> list[ActionOut]:
    connections = {c.id: c for c in ctx.repos.connections.list(workspace_id=ctx.id)}
    return [_out(a, connections) for a in ctx.repos.actions.list(workspace_id=ctx.id)]


@router.post("", status_code=201)
def create(body: ActionIn, ctx: WorkspaceDep) -> ActionOut:
    conn = _connection(ctx, body.connection_id)
    _check_operation(conn, body.operation)
    action = ctx.repos.actions.create(
        Action(workspace_id=ctx.id, **{**body.model_dump(), "name": body.name.strip()})
    )
    return _out(action, {conn.id: conn})


@router.get("/{action_id}")
def get(action_id: str, ctx: WorkspaceDep) -> ActionOut:
    return _one(ctx, scoped(ctx.repos.actions, action_id, ctx, "action"))


@router.patch("/{action_id}")
def update(action_id: str, body: ActionPatch, ctx: WorkspaceDep) -> ActionOut:
    action = scoped(ctx.repos.actions, action_id, ctx, "action")
    changes: dict[str, Any] = {
        k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None
    }
    if "connection_id" in changes or "operation" in changes:
        conn = _connection(ctx, changes.get("connection_id", action.connection_id))
        _check_operation(conn, changes.get("operation", action.operation))
    if changes:
        action = ctx.repos.actions.update(action.id, **changes)
    return _one(ctx, action)


@router.delete("/{action_id}", status_code=204)
def delete(action_id: str, ctx: WorkspaceDep) -> None:
    action = scoped(ctx.repos.actions, action_id, ctx, "action")
    users = [
        op.name
        for op in ctx.repos.operators.list(workspace_id=ctx.id)
        if any(t.action_id == action.id for t in op.tasks)
    ]
    if users:
        raise HTTPException(
            409, f"action is used by {len(users)} operator(s): {', '.join(users[:5])}"
        )
    ctx.repos.actions.delete(action.id)
    for agent in ctx.repos.agents.list(workspace_id=ctx.id):
        if action.id in agent.action_ids:
            ctx.repos.agents.update(
                agent.id, action_ids=[i for i in agent.action_ids if i != action.id]
            )


@router.post("/{action_id}/run", status_code=202)
def run(action_id: str, ctx: WorkspaceDep, body: RunIn | None = Body(default=None)) -> RunOut:
    scoped(ctx.repos.actions, action_id, ctx, "action")
    return start_run(ctx, "action", action_id, body.input if body else {})
