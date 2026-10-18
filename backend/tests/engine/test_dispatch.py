import pytest

from anexa.engine.dispatch import TargetNotFound, submit_run
from anexa.models import OperatorTask


def test_submit_action_run_executes_eagerly(repos, fake, make_action, ws):
    action = make_action("echo", {"who": "{{ input.who }}"}, name="Echo")

    run = submit_run(
        repos, ws, "action", action.id, trigger="mcp", triggered_by="key1", input={"who": "al"}
    )

    assert run.status == "succeeded"
    assert (run.kind, run.target_id, run.target_name) == ("action", action.id, "Echo")
    assert (run.trigger, run.triggered_by, run.input) == ("mcp", "key1", {"who": "al"})
    assert run.output["params"] == {"who": "al"}
    assert repos.runs.list(workspace_id=ws) == [run]


def test_submit_operator_run_executes_eagerly(repos, fake, make_action, make_operator, ws):
    operator = make_operator([OperatorTask(key="a", action_id=make_action("echo").id)], name="Op")
    run = submit_run(repos, ws, "operator", operator.id)
    assert run.status == "succeeded" and run.target_name == "Op"
    assert run.trigger == "manual" and run.input == {}
    assert [t.status for t in run.tasks] == ["succeeded"]


def test_failed_run_is_returned_not_raised(repos, fake, make_action, ws):
    run = submit_run(repos, ws, "action", make_action("fail").id)
    assert run.status == "failed" and run.error == "upstream said no"


@pytest.mark.parametrize("kind", ["action", "operator"])
def test_unknown_target(repos, fake, ws, kind):
    with pytest.raises(TargetNotFound):
        submit_run(repos, ws, kind, "nope")
    assert repos.runs.list() == []


def test_target_in_another_workspace(repos, fake, make_action):
    action = make_action("echo")
    with pytest.raises(TargetNotFound):
        submit_run(repos, "other", "action", action.id)
    assert repos.runs.list() == []


def test_run_is_queued_before_the_task_is_sent(repos, fake, make_action, ws, monkeypatch):
    from anexa.worker import tasks

    sent = []
    monkeypatch.setattr(tasks.execute_run, "delay", lambda run_id: sent.append(run_id))

    run = submit_run(repos, ws, "action", make_action("echo").id)

    assert sent == [run.id]
    assert run.status == "queued" and run.started_at is None
