from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...models import Operator, Schedule
from ...scheduling import next_fire, validate_schedule
from ..common import invalid, scoped
from ..deps import WorkspaceCtx, WorkspaceDep
from ..schemas import ScheduleIn, ScheduleOut, SchedulePatch

router = APIRouter(prefix="/api/workspaces/{ws}/schedules", tags=["schedules"])


def _out(schedule: Schedule, operators: dict[str, Operator]) -> ScheduleOut:
    op = operators.get(schedule.operator_id)
    return ScheduleOut(
        **schedule.model_dump(exclude={"workspace_id"}), operator_name=op.name if op else ""
    )


def _one(ctx: WorkspaceCtx, schedule: Schedule) -> ScheduleOut:
    op = ctx.repos.operators.get(schedule.operator_id)
    return _out(schedule, {op.id: op} if op else {})


def _next(cron: str, timezone: str, enabled: bool) -> str | None:
    try:
        validate_schedule(cron, timezone)
        return next_fire(cron, timezone) if enabled else None
    except ValueError as exc:
        raise invalid(str(exc)) from exc


@router.get("")
def list_schedules(ctx: WorkspaceDep, operator_id: str | None = None) -> list[ScheduleOut]:
    where = {"operator_id": operator_id} if operator_id else {}
    operators = {o.id: o for o in ctx.repos.operators.list(workspace_id=ctx.id)}
    return [_out(s, operators) for s in ctx.repos.schedules.list(workspace_id=ctx.id, **where)]


@router.post("", status_code=201)
def create(body: ScheduleIn, ctx: WorkspaceDep) -> ScheduleOut:
    op = ctx.repos.operators.get(body.operator_id)
    if op is None or op.workspace_id != ctx.id:
        raise invalid(f"operator {body.operator_id!r} does not exist in this workspace")
    cron = " ".join(body.cron.split())
    schedule = Schedule(
        workspace_id=ctx.id,
        operator_id=op.id,
        cron=cron,
        timezone=body.timezone,
        enabled=body.enabled,
        input=body.input,
        next_run_at=_next(cron, body.timezone, body.enabled),
    )
    return _out(ctx.repos.schedules.create(schedule), {op.id: op})


@router.get("/{schedule_id}")
def get(schedule_id: str, ctx: WorkspaceDep) -> ScheduleOut:
    return _one(ctx, scoped(ctx.repos.schedules, schedule_id, ctx, "schedule"))


@router.patch("/{schedule_id}")
def update(schedule_id: str, body: SchedulePatch, ctx: WorkspaceDep) -> ScheduleOut:
    schedule = scoped(ctx.repos.schedules, schedule_id, ctx, "schedule")
    changes: dict[str, Any] = {
        k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None
    }
    if "cron" in changes:
        changes["cron"] = " ".join(changes["cron"].split())
    if changes.keys() & {"cron", "timezone", "enabled"}:
        changes["next_run_at"] = _next(
            changes.get("cron", schedule.cron),
            changes.get("timezone", schedule.timezone),
            changes.get("enabled", schedule.enabled),
        )
    if changes:
        schedule = ctx.repos.schedules.update(schedule.id, **changes)
    return _one(ctx, schedule)


@router.delete("/{schedule_id}", status_code=204)
def delete(schedule_id: str, ctx: WorkspaceDep) -> None:
    schedule = scoped(ctx.repos.schedules, schedule_id, ctx, "schedule")
    ctx.repos.schedules.delete(schedule.id)
