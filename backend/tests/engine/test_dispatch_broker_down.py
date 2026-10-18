from anexa.engine import dispatch
from anexa.models import Action, Connection
from anexa.worker import tasks


def test_run_is_failed_not_stuck_when_broker_is_down(repos, monkeypatch):
    conn = repos.connections.create(Connection(workspace_id="w1", name="c", connector="agent"))
    action = repos.actions.create(
        Action(workspace_id="w1", name="a", connection_id=conn.id, operation="invoke")
    )

    def boom(run_id):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks.execute_run, "delay", boom)

    run = dispatch.submit_run(repos, "w1", "action", action.id)

    assert run.status == "failed"
    assert "broker unreachable" in run.error
    assert repos.runs.get(run.id).status == "failed"
