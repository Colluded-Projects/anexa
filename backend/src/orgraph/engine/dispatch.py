"""The single entry point for starting work. The API, the scheduler and the
MCP server (through the API) all go through `submit_run`."""

from __future__ import annotations

from typing import Any

from ..models import Run, RunKind, RunTrigger, utcnow
from ..repos import Repos


class TargetNotFound(Exception):
    pass


def submit_run(
    repos: Repos,
    workspace_id: str,
    kind: RunKind,
    target_id: str,
    *,
    trigger: RunTrigger = "manual",
    triggered_by: str | None = None,
    input: dict[str, Any] | None = None,
) -> Run:
    """Record a queued Run for an Action or Operator and hand it to Celery.
    Returns the queued Run (already finished when Celery runs eagerly).
    Raises TargetNotFound if the target is not in the workspace."""
    repo = repos.actions if kind == "action" else repos.operators
    target = repo.get(target_id)
    if target is None or target.workspace_id != workspace_id:
        raise TargetNotFound(f"{kind} {target_id!r} not found")

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

    from ..worker.tasks import execute_run  # imported late: worker imports the engine

    try:
        execute_run.delay(run.id)
    except Exception as exc:  # broker unreachable: don't leave the run queued forever
        return repos.runs.update(
            run.id,
            status="failed",
            error=f"could not queue run: {type(exc).__name__}: {exc}",
            finished_at=utcnow(),
        )
    return repos.runs.get(run.id) or run
