from datetime import UTC, datetime, timedelta

import pytest

from orgraph.models import OperatorTask, Run, Schedule
from orgraph.worker import tasks
from orgraph.worker.celery_app import celery_app
from orgraph.worker.tasks import NoLock, RedisLock, run_scheduler_tick

NOW = datetime(2026, 1, 5, 12, 0, 30, tzinfo=UTC)
PAST = "2026-01-05T12:00:00.000Z"
FUTURE = "2026-01-05T13:00:00.000Z"


@pytest.fixture
def operator(fake, make_action, make_operator):
    action = make_action("echo", {"who": "{{ input.who }}"})
    return make_operator([OperatorTask(key="a", action_id=action.id)], name="Digest")


@pytest.fixture
def schedule(repos, ws):
    def make(operator_id, next_run_at=PAST, **kwargs) -> Schedule:
        kwargs.setdefault("cron", "0 * * * *")
        kwargs.setdefault("input", {"who": "cron"})
        kwargs.setdefault("workspace_id", ws)
        return repos.schedules.create(
            Schedule(operator_id=operator_id, next_run_at=next_run_at, **kwargs)
        )

    return make


def tick(repos, now=NOW, lock=None):
    return run_scheduler_tick(repos, now=now, lock=lock or NoLock())


# --- celery wiring -----------------------------------------------------------


def test_celery_is_configured_from_settings(settings):
    conf = celery_app.conf
    assert conf.task_always_eager is True
    assert conf.broker_url == settings.redis_url
    assert conf.task_serializer == "json" and conf.accept_content == ["json"]
    assert conf.timezone == "UTC" and conf.task_acks_late is True
    entry = conf.beat_schedule["scheduler-tick"]
    assert entry["task"] == "orgraph.scheduler_tick"
    assert entry["schedule"] == settings.scheduler_tick_seconds
    assert {"orgraph.execute_run", "orgraph.scheduler_tick"} <= set(celery_app.tasks)


def test_execute_run_task(repos, fake, make_action, ws):
    run = repos.runs.create(Run(workspace_id=ws, kind="action", target_id=make_action("echo").id))
    result = tasks.execute_run.delay(run.id)
    assert result.get() == {"id": run.id, "status": "succeeded"}
    assert repos.runs.get(run.id).status == "succeeded"


def test_execute_run_task_tolerates_deleted_run(repos, fake):
    assert tasks.execute_run.delay("gone").get() == {"id": "gone", "status": "missing"}


def test_scheduler_tick_task_uses_process_store(repos, operator, schedule):
    sched = schedule(operator.id, next_run_at="2000-01-01T00:00:00.000Z")
    summary = tasks.scheduler_tick.delay().get()
    assert [f["schedule_id"] for f in summary["fired"]] == [sched.id]


# --- scheduler ---------------------------------------------------------------


def test_due_schedule_fires_and_advances(repos, operator, schedule, ws):
    sched = schedule(operator.id)

    summary = tick(repos)

    [run] = repos.runs.list()
    assert summary["fired"] == [{"schedule_id": sched.id, "run_id": run.id}]
    assert (run.kind, run.target_id, run.workspace_id) == ("operator", operator.id, ws)
    assert (run.trigger, run.triggered_by, run.input) == ("schedule", sched.id, {"who": "cron"})
    assert run.status == "succeeded" and run.tasks[0].output["params"] == {"who": "cron"}
    stored = repos.schedules.get(sched.id)
    assert stored.last_run_at == "2026-01-05T12:00:30.000Z"
    assert stored.next_run_at == FUTURE


def test_schedule_due_exactly_now_fires(repos, operator, schedule):
    schedule(operator.id, next_run_at="2026-01-05T12:00:30.000Z")
    assert len(tick(repos)["fired"]) == 1


def test_not_due_schedule_is_left_alone(repos, operator, schedule):
    sched = schedule(operator.id, next_run_at=FUTURE)
    assert tick(repos)["fired"] == []
    assert repos.runs.list() == []
    assert repos.schedules.get(sched.id) == sched


def test_second_tick_does_not_fire_again(repos, operator, schedule):
    schedule(operator.id)
    tick(repos)
    tick(repos, NOW + timedelta(seconds=30))
    assert len(repos.runs.list()) == 1


def test_missed_intervals_are_not_replayed(repos, operator, schedule):
    sched = schedule(operator.id, next_run_at="2026-01-01T00:00:00.000Z")
    tick(repos)
    tick(repos, NOW + timedelta(seconds=30))
    assert len(repos.runs.list()) == 1
    assert repos.schedules.get(sched.id).next_run_at == FUTURE


def test_fires_again_at_next_interval(repos, operator, schedule):
    schedule(operator.id)
    tick(repos)
    tick(repos, NOW + timedelta(hours=1))
    assert len(repos.runs.list()) == 2


def test_disabled_schedule_does_not_fire(repos, operator, schedule):
    sched = schedule(operator.id, enabled=False)
    assert tick(repos)["fired"] == []
    assert repos.schedules.get(sched.id) == sched


@pytest.mark.parametrize("case", ["missing", "disabled", "other_workspace"])
def test_unrunnable_operator_is_advanced_but_not_run(repos, operator, schedule, case):
    if case == "missing":
        sched = schedule("gone")
    elif case == "disabled":
        repos.operators.update(operator.id, enabled=False)
        sched = schedule(operator.id)
    else:
        sched = schedule(operator.id, workspace_id="other")

    summary = tick(repos)

    assert summary["fired"] == [] and summary["skipped"] == [sched.id]
    assert repos.runs.list() == []
    stored = repos.schedules.get(sched.id)
    assert stored.next_run_at == FUTURE and stored.last_run_at is None


def test_enabled_schedule_without_next_run_gets_one(repos, operator, schedule):
    sched = schedule(operator.id, next_run_at=None)
    assert tick(repos)["fired"] == []
    assert repos.schedules.get(sched.id).next_run_at == FUTURE
    assert repos.runs.list() == []


def test_timezone_is_respected_when_advancing(repos, operator, schedule):
    sched = schedule(operator.id, cron="0 9 * * *", timezone="America/New_York")
    tick(repos)
    assert repos.schedules.get(sched.id).next_run_at == "2026-01-05T14:00:00.000Z"


def test_bad_schedule_does_not_stop_the_others(repos, operator, schedule):
    bad = schedule(operator.id, cron="not a cron")
    good = schedule(operator.id)

    summary = tick(repos)

    assert [f["schedule_id"] for f in summary["fired"]] == [good.id]
    assert [e["schedule_id"] for e in summary["errors"]] == [bad.id]
    assert len(repos.runs.list()) == 1


def test_submit_failure_does_not_stop_the_others(repos, operator, schedule, monkeypatch):
    first, second = schedule(operator.id), schedule(operator.id)
    real = tasks.submit_run
    calls = []

    def flaky(*args, **kwargs):
        calls.append(kwargs["triggered_by"])
        if len(calls) == 1:
            raise ConnectionError("broker down")
        return real(*args, **kwargs)

    monkeypatch.setattr(tasks, "submit_run", flaky)
    summary = tick(repos)

    assert len(calls) == 2 and {first.id, second.id} == set(calls)
    assert [e["schedule_id"] for e in summary["errors"]] == [calls[0]]
    assert [f["schedule_id"] for f in summary["fired"]] == [calls[1]]


def test_failing_run_still_counts_as_fired(repos, fake, make_action, make_operator, schedule):
    operator = make_operator([OperatorTask(key="a", action_id=make_action("fail").id)])
    sched = schedule(operator.id)
    assert len(tick(repos)["fired"]) == 1
    assert repos.runs.list()[0].status == "failed"
    assert repos.schedules.get(sched.id).last_run_at


# --- locking -----------------------------------------------------------------


class HeldLock:
    released = False

    def acquire(self):
        return False

    def release(self):
        self.released = True


def test_tick_does_nothing_when_lock_is_held(repos, operator, schedule):
    sched = schedule(operator.id)
    lock = HeldLock()
    summary = tick(repos, lock=lock)
    assert summary["locked"] is True and summary["fired"] == []
    assert repos.runs.list() == [] and repos.schedules.get(sched.id) == sched
    assert lock.released is False


def test_lock_is_released_even_when_tick_breaks(repos, monkeypatch):
    events = []

    class Lock:
        def acquire(self):
            events.append("acquire")
            return True

        def release(self):
            events.append("release")

    monkeypatch.setattr(repos.schedules, "list", lambda **kw: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        tick(repos, lock=Lock())
    assert events == ["acquire", "release"]


def test_redis_lock_is_exclusive_and_only_releases_its_own():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis()
    first, second = RedisLock(client, ttl_seconds=30), RedisLock(client, ttl_seconds=30)

    assert first.acquire() is True
    assert second.acquire() is False
    assert 0 < client.ttl(tasks.TICK_LOCK_KEY) <= 30
    second.release()  # not the holder: must not free it
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True


def test_two_ticks_with_shared_redis_lock_fire_once(repos, operator, schedule):
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis()
    schedule(operator.id)
    holder = RedisLock(client)
    assert holder.acquire()
    assert tick(repos, lock=RedisLock(client))["locked"] is True
    holder.release()
    assert len(tick(repos, lock=RedisLock(client))["fired"]) == 1
    assert len(repos.runs.list()) == 1
