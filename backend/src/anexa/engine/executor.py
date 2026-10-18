"""Runs an Action or an Operator and records the outcome on its Run.

Progress is persisted after every state change so the UI can poll a run while
it executes. Nothing here raises for a failing task: failures end up in the
run's `error` and the task's `error`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import httpx

from ..config import Settings
from ..connectors import ConnectorContext, ConnectorError, OperationResult, get_connector
from ..graph.ingest import apply_delta
from ..models import Action, Run, TaskResult, utcnow
from ..repos import Repos
from ..security import decrypt_secrets
from .templating import TemplateError, render

log = logging.getLogger(__name__)

HttpFactory = Callable[[Settings], httpx.Client]


def default_http_factory(settings: Settings) -> httpx.Client:
    return httpx.Client(timeout=settings.connector_timeout_seconds, follow_redirects=True)


class TaskFailure(Exception):
    """A task cannot run for a reason the user can fix."""


def execute_run(repos: Repos, run_id: str, *, http_factory: HttpFactory | None = None) -> Run:
    """Execute the queued run `run_id` to completion and return it.
    A run that already finished is returned untouched. Raises LookupError if
    the run does not exist."""
    run = repos.runs.get(run_id)
    if run is None:
        raise LookupError(f"run {run_id!r} not found")
    if run.status in ("succeeded", "failed"):
        return run

    run = repos.runs.update(
        run.id, status="running", started_at=utcnow(), error=None, output=None, tasks=[]
    )
    try:
        if run.kind == "action":
            return _run_action_kind(repos, run, http_factory or default_http_factory)
        return _run_operator_kind(repos, run, http_factory or default_http_factory)
    except Exception as exc:  # the run must never stay "running"
        log.exception("run %s crashed", run.id)
        current = repos.runs.get(run.id) or run
        return _finish(repos, run, _skip_pending(current.tasks), error=_describe(exc))


# --- run kinds ---------------------------------------------------------------


def _run_action_kind(repos: Repos, run: Run, http_factory: HttpFactory) -> Run:
    action = _owned(repos.actions.get(run.target_id), run.workspace_id)
    task = TaskResult(
        key="action", action_id=run.target_id, action_name=action.name if action else ""
    )
    _execute_task(repos, run, [task], task, {}, _context(run, []), http_factory)
    return _finish(repos, run, [task], error=task.error, output=task.output)


def _run_operator_kind(repos: Repos, run: Run, http_factory: HttpFactory) -> Run:
    operator = _owned(repos.operators.get(run.target_id), run.workspace_id)
    if operator is None:
        return _finish(repos, run, [], error=f"operator {run.target_id!r} not found")

    tasks = []
    for spec in operator.tasks:
        action = _owned(repos.actions.get(spec.action_id), run.workspace_id)
        tasks.append(
            TaskResult(
                key=spec.key, action_id=spec.action_id, action_name=action.name if action else ""
            )
        )
    if not operator.enabled:
        return _finish(repos, run, _skip_pending(tasks), error="operator is disabled")
    repos.runs.update(run.id, tasks=tasks)

    error = None
    for spec, task in zip(operator.tasks, tasks, strict=True):
        _execute_task(repos, run, tasks, task, spec.params, _context(run, tasks), http_factory)
        if task.status == "failed" and not spec.continue_on_error:
            error = f"task {task.key!r} failed: {task.error}"
            _skip_pending(tasks)
            break

    output = {t.key: t.output for t in tasks if t.status == "succeeded"}
    return _finish(repos, run, tasks, error=error, output=output)


# --- one task ----------------------------------------------------------------


def _execute_task(
    repos: Repos,
    run: Run,
    tasks: list[TaskResult],
    task: TaskResult,
    params: dict[str, Any],
    context: dict[str, Any],
    http_factory: HttpFactory,
) -> None:
    """Run one task, updating `task` in place and persisting `tasks` around it."""
    task.status, task.started_at = "running", utcnow()
    repos.runs.update(run.id, tasks=tasks)
    try:
        task.output = _call_action(
            repos, run.workspace_id, task.action_id, params, context, http_factory
        )
        task.status = "succeeded"
    except Exception as exc:
        if not isinstance(exc, ConnectorError | TemplateError | TaskFailure):
            log.exception("run %s task %s raised", run.id, task.key)
        task.status, task.error = "failed", _describe(exc)
    task.finished_at = utcnow()
    repos.runs.update(run.id, tasks=tasks)


def _call_action(
    repos: Repos,
    workspace_id: str,
    action_id: str,
    params: dict[str, Any],
    context: dict[str, Any],
    http_factory: HttpFactory,
) -> dict[str, Any]:
    action: Action | None = _owned(repos.actions.get(action_id), workspace_id)
    if action is None:
        raise TaskFailure(f"action {action_id!r} not found")
    connection = _owned(repos.connections.get(action.connection_id), workspace_id)
    if connection is None:
        raise TaskFailure(f"connection {action.connection_id!r} not found")

    connector = get_connector(connection.connector)
    rendered = render({**action.params, **params}, context)
    connector.validate_params(action.operation, rendered)
    try:
        secrets = decrypt_secrets(connection.secrets_enc, repos.settings)
    except ValueError as exc:
        raise TaskFailure(f"connection {connection.name!r}: {exc}") from exc

    with http_factory(repos.settings) as http:
        ctx = ConnectorContext(config=dict(connection.config), secrets=secrets, http=http)
        result = connector.execute(action.operation, rendered, ctx)
    if not isinstance(result, OperationResult):
        raise TypeError(f"{connection.connector}.{action.operation} did not return a result")

    # Round-trip so whatever is stored on the run is plain JSON.
    output: dict[str, Any] = json.loads(json.dumps(result.output, default=str))
    if result.graph is not None:
        output["graph"] = apply_delta(
            repos.store, repos.company_graph(workspace_id), result.graph, connection.connector
        )
    return output


# --- helpers -----------------------------------------------------------------


def _owned[T](obj: T | None, workspace_id: str) -> T | None:
    return obj if obj is not None and obj.workspace_id == workspace_id else None


def _context(run: Run, tasks: list[TaskResult]) -> dict[str, Any]:
    return {
        "input": run.input,
        "run": {"id": run.id, "started_at": run.started_at},
        "tasks": {
            t.key: {"output": t.output, "status": t.status}
            for t in tasks
            if t.status in ("succeeded", "failed")
        },
    }


def _skip_pending(tasks: list[TaskResult]) -> list[TaskResult]:
    for task in tasks:
        if task.status == "pending":
            task.status = "skipped"
    return tasks


def _describe(exc: Exception) -> str:
    name = type(exc).__name__
    if isinstance(exc, ConnectorError | TemplateError | TaskFailure):
        return str(exc) or name
    return f"{name}: {exc}"


def _finish(
    repos: Repos,
    run: Run,
    tasks: list[TaskResult],
    *,
    error: str | None,
    output: dict[str, Any] | None = None,
) -> Run:
    return repos.runs.update(
        run.id,
        status="failed" if error else "succeeded",
        error=error,
        output=output,
        tasks=tasks,
        finished_at=utcnow(),
    )
