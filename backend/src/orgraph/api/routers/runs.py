from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...models import RunKind, RunStatus
from ..common import run_out, scoped
from ..deps import WorkspaceDep
from ..schemas import RunOut

router = APIRouter(prefix="/api/workspaces/{ws}/runs", tags=["runs"])


@router.get("")
def list_runs(
    ctx: WorkspaceDep,
    kind: RunKind | None = None,
    target_id: str | None = None,
    status: RunStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[RunOut]:
    where = {"kind": kind, "target_id": target_id, "status": status}
    runs = ctx.repos.runs.list(
        workspace_id=ctx.id, limit=limit, **{k: v for k, v in where.items() if v}
    )
    return [run_out(r) for r in runs]


@router.get("/{run_id}")
def get(run_id: str, ctx: WorkspaceDep) -> RunOut:
    return run_out(scoped(ctx.repos.runs, run_id, ctx, "run"))
