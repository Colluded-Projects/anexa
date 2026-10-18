from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from ...models import Operator, OperatorTask
from ..common import invalid, scoped, start_run
from ..deps import WorkspaceCtx, WorkspaceDep
from ..schemas import OperatorIn, OperatorOut, OperatorPatch, RunIn, RunOut, TaskIn

router = APIRouter(prefix="/api/workspaces/{ws}/operators", tags=["operators"])


def _out(op: Operator) -> OperatorOut:
    return OperatorOut(**op.model_dump(exclude={"workspace_id"}))


def _tasks(ctx: WorkspaceCtx, tasks: list[TaskIn]) -> list[OperatorTask]:
    keys = [t.key for t in tasks]
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    if dupes:
        raise invalid(f"duplicate task keys: {', '.join(dupes)}")
    for task in tasks:
        action = ctx.repos.actions.get(task.action_id)
        if action is None or action.workspace_id != ctx.id:
            raise invalid(
                f"task {task.key!r}: action {task.action_id!r} does not exist in this workspace"
            )
    return [OperatorTask(**t.model_dump()) for t in tasks]


@router.get("")
def list_operators(ctx: WorkspaceDep) -> list[OperatorOut]:
    return [_out(o) for o in ctx.repos.operators.list(workspace_id=ctx.id)]


@router.post("", status_code=201)
def create(body: OperatorIn, ctx: WorkspaceDep) -> OperatorOut:
    op = Operator(
        workspace_id=ctx.id,
        name=body.name.strip(),
        description=body.description,
        tasks=_tasks(ctx, body.tasks),
        enabled=body.enabled,
    )
    return _out(ctx.repos.operators.create(op))


@router.get("/{operator_id}")
def get(operator_id: str, ctx: WorkspaceDep) -> OperatorOut:
    return _out(scoped(ctx.repos.operators, operator_id, ctx, "operator"))


@router.patch("/{operator_id}")
def update(operator_id: str, body: OperatorPatch, ctx: WorkspaceDep) -> OperatorOut:
    op = scoped(ctx.repos.operators, operator_id, ctx, "operator")
    changes: dict[str, Any] = {
        k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None
    }
    if body.tasks is not None:
        changes["tasks"] = [t.model_dump() for t in _tasks(ctx, body.tasks)]
    return _out(ctx.repos.operators.update(op.id, **changes) if changes else op)


@router.delete("/{operator_id}", status_code=204)
def delete(operator_id: str, ctx: WorkspaceDep) -> None:
    op = scoped(ctx.repos.operators, operator_id, ctx, "operator")
    for schedule in ctx.repos.schedules.list(workspace_id=ctx.id, operator_id=op.id):
        ctx.repos.schedules.delete(schedule.id)
    ctx.repos.operators.delete(op.id)
    for agent in ctx.repos.agents.list(workspace_id=ctx.id):
        if op.id in agent.operator_ids:
            ctx.repos.agents.update(
                agent.id, operator_ids=[i for i in agent.operator_ids if i != op.id]
            )


@router.post("/{operator_id}/run", status_code=202)
def run(operator_id: str, ctx: WorkspaceDep, body: RunIn | None = Body(default=None)) -> RunOut:
    scoped(ctx.repos.operators, operator_id, ctx, "operator")
    return start_run(ctx, "operator", operator_id, body.input if body else {})
