from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from ..engine import dispatch
from ..models import Run, RunKind, User, Workspace, WorkspaceScoped
from ..repos import Repo
from .deps import WorkspaceCtx
from .schemas import RunOut, UserOut, WorkspaceOut

log = logging.getLogger(__name__)


def invalid(detail: str) -> HTTPException:
    return HTTPException(422, detail)


def scoped[T: WorkspaceScoped](repo: Repo[T], id: str, ctx: WorkspaceCtx, what: str) -> T:
    """Fetch a resource, answering 404 unless it belongs to the caller's workspace."""
    obj = repo.get(id)
    if obj is None or obj.workspace_id != ctx.id:
        raise HTTPException(404, f"{what} not found")
    return obj


def user_out(user: User) -> UserOut:
    return UserOut(**user.model_dump(include={"id", "email", "name", "created_at"}))


def workspace_out(ws: Workspace, role: str) -> WorkspaceOut:
    return WorkspaceOut(id=ws.id, name=ws.name, slug=ws.slug, role=role, created_at=ws.created_at)


def run_out(run: Run) -> RunOut:
    return RunOut(**run.model_dump(exclude={"workspace_id", "updated_at"}))


def start_run(ctx: WorkspaceCtx, kind: RunKind, target_id: str, input: dict[str, Any]) -> RunOut:
    try:
        run = dispatch.submit_run(
            ctx.repos,
            ctx.id,
            kind,
            target_id,
            trigger="mcp" if ctx.principal.via == "api_key" else "manual",
            triggered_by=ctx.principal.user.id,
            input=input,
        )
    except dispatch.TargetNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # broker unreachable, worker module broken, ...
        log.exception("could not queue %s run for %s", kind, target_id)
        raise HTTPException(503, f"could not queue run: {exc}") from exc
    return run_out(run)
