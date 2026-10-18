from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from celery.exceptions import SoftTimeLimitExceeded

from ..config import Settings, get_settings
from ..engine import executor
from ..engine.dispatch import TargetNotFound, submit_run
from ..models import utcnow
from ..repos import Repos
from ..scheduling import next_fire
from .celery_app import celery_app

log = logging.getLogger(__name__)

TICK_LOCK_KEY = "anexa:scheduler-tick"


@celery_app.task(name="anexa.execute_run")
def execute_run(run_id: str) -> dict[str, Any]:
    repos = Repos()
    try:
        run = executor.execute_run(repos, run_id)
    except LookupError:
        log.warning("run %s no longer exists", run_id)
        return {"id": run_id, "status": "missing"}
    except SoftTimeLimitExceeded:
        run = repos.runs.update(
            run_id, status="failed", error="run exceeded the time limit", finished_at=utcnow()
        )
    return {"id": run.id, "status": run.status}


# --- scheduler ---------------------------------------------------------------


class TickLock(Protocol):
    def acquire(self) -> bool: ...
    def release(self) -> None: ...


class NoLock:
    def acquire(self) -> bool:
        return True

    def release(self) -> None:
        pass


class RedisLock:
    """SET NX with a TTL, so a crashed tick cannot hold the lock forever."""

    def __init__(self, client: Any, key: str = TICK_LOCK_KEY, ttl_seconds: int = 60) -> None:
        self.client, self.key, self.ttl = client, key, ttl_seconds
        self.token = uuid.uuid4().hex

    def acquire(self) -> bool:
        return bool(self.client.set(self.key, self.token, nx=True, ex=self.ttl))

    def release(self) -> None:
        """Delete the key only if this lock still holds it."""
        from redis.exceptions import WatchError

        with self.client.pipeline() as pipe:
            try:
                pipe.watch(self.key)
                held = pipe.get(self.key)
                if isinstance(held, bytes):
                    held = held.decode()
                if held == self.token:
                    pipe.multi()
                    pipe.delete(self.key)
                    pipe.execute()
            except WatchError:
                pass  # expired and taken by someone else in the meantime


def default_lock(settings: Settings) -> TickLock:
    if settings.celery_eager:
        return NoLock()
    import redis

    return RedisLock(
        redis.Redis.from_url(settings.redis_url),
        ttl_seconds=max(settings.scheduler_tick_seconds, 30),
    )


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_scheduler_tick(
    repos: Repos, *, now: datetime | None = None, lock: TickLock | None = None
) -> dict[str, Any]:
    """Start one operator run for every enabled schedule that is due.

    A schedule is advanced to its next fire time *before* its run is submitted,
    so an overlapping tick cannot fire it twice. Intervals missed while the
    scheduler was down are not replayed."""
    lock = lock or default_lock(repos.settings)
    if not lock.acquire():
        return {"locked": True, "fired": [], "skipped": [], "errors": []}
    now = now or datetime.now(UTC)
    now_iso = _iso(now)
    summary: dict[str, Any] = {"locked": False, "fired": [], "skipped": [], "errors": []}
    try:
        for schedule in repos.schedules.list(enabled=True, desc=False):
            try:
                if schedule.next_run_at is None:
                    upcoming = next_fire(schedule.cron, schedule.timezone, now)
                    repos.schedules.update(schedule.id, next_run_at=upcoming)
                    continue
                if schedule.next_run_at > now_iso:
                    continue

                # Claim it: skip if another tick already advanced this schedule.
                fresh = repos.schedules.get(schedule.id)
                if fresh is None or not fresh.enabled or fresh.next_run_at != schedule.next_run_at:
                    continue
                repos.schedules.update(
                    schedule.id, next_run_at=next_fire(schedule.cron, schedule.timezone, now)
                )

                operator = repos.operators.get(schedule.operator_id)
                if (
                    operator is None
                    or operator.workspace_id != schedule.workspace_id
                    or not operator.enabled
                ):
                    summary["skipped"].append(schedule.id)
                    continue
                run = submit_run(
                    repos,
                    schedule.workspace_id,
                    "operator",
                    schedule.operator_id,
                    trigger="schedule",
                    triggered_by=schedule.id,
                    input=schedule.input,
                )
                repos.schedules.update(schedule.id, last_run_at=now_iso)
                summary["fired"].append({"schedule_id": schedule.id, "run_id": run.id})
            except TargetNotFound:
                summary["skipped"].append(schedule.id)
            except Exception as exc:  # one bad schedule must not stop the others
                log.exception("schedule %s failed to fire", schedule.id)
                summary["errors"].append({"schedule_id": schedule.id, "error": str(exc)})
    finally:
        lock.release()
    return summary


@celery_app.task(name="anexa.scheduler_tick")
def scheduler_tick() -> dict[str, Any]:
    return run_scheduler_tick(Repos(settings=get_settings()))
