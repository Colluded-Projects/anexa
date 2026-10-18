import httpx
import pytest

from anexa.config import Settings
from anexa.engine.executor import execute_run
from anexa.models import OperatorTask, Run
from anexa.security import encrypt_secrets


@pytest.fixture
def queue(repos, ws):
    def make(kind, target_id, input=None, workspace_id=ws) -> Run:
        return repos.runs.create(
            Run(workspace_id=workspace_id, kind=kind, target_id=target_id, input=input or {})
        )

    return make


def task(key, action, **kwargs):
    return OperatorTask(key=key, action_id=action.id, **kwargs)


# --- action runs -------------------------------------------------------------


def test_action_run_succeeds(repos, fake, make_action, queue):
    action = make_action("echo", {"text": "hi {{ input.who }}", "n": "{{ input.n }}"}, name="Echo")
    run = execute_run(repos, queue("action", action.id, {"who": "bob", "n": 2}).id)

    assert run.status == "succeeded"
    assert run.error is None
    assert run.output == {"params": {"text": "hi bob", "n": 2}, "secrets": {"token": "s3cret"}}
    assert run.started_at and run.finished_at and run.started_at <= run.finished_at
    [result] = run.tasks
    assert (result.key, result.action_id, result.action_name) == ("action", action.id, "Echo")
    assert result.status == "succeeded" and result.output == run.output
    assert result.started_at and result.finished_at
    assert repos.runs.get(run.id) == run


def test_run_context_exposes_run_id(repos, fake, make_action, queue):
    action = make_action("echo", {"id": "{{ run.id }}", "at": "{{ run.started_at }}"})
    run = execute_run(repos, queue("action", action.id).id)
    assert run.output["params"] == {"id": run.id, "at": run.started_at}


def test_connector_gets_config_secrets_and_closed_client(
    repos, fake, make_connection, make_action, queue
):
    connection = make_connection(config={"base_url": "https://x.test"})
    action = make_action("echo", connection_id=connection.id)
    clients = []

    def factory(settings: Settings) -> httpx.Client:
        clients.append(httpx.Client(timeout=settings.connector_timeout_seconds))
        return clients[-1]

    execute_run(repos, queue("action", action.id).id, http_factory=factory)

    _, _, ctx = fake.calls[0]
    assert ctx.config == {"base_url": "https://x.test"}
    assert ctx.secrets == {"token": "s3cret"}
    assert ctx.http is clients[0] and clients[0].is_closed


def test_client_closed_when_connector_raises(repos, fake, make_action, queue):
    clients = []

    def factory(settings):
        clients.append(httpx.Client())
        return clients[-1]

    execute_run(repos, queue("action", make_action("boom").id).id, http_factory=factory)
    assert clients[0].is_closed


def test_connector_error_fails_run(repos, fake, make_action, queue):
    run = execute_run(repos, queue("action", make_action("fail").id).id)
    assert run.status == "failed"
    assert run.error == "upstream said no"
    assert run.output is None
    assert run.tasks[0].status == "failed" and run.tasks[0].error == "upstream said no"
    assert run.finished_at


def test_unexpected_exception_is_recorded_with_type(repos, fake, make_action, queue):
    run = execute_run(repos, queue("action", make_action("boom").id).id)
    assert run.status == "failed"
    assert run.error == "RuntimeError: kaboom"


def test_unresolved_template_fails_before_calling_connector(repos, fake, make_action, queue):
    action = make_action("echo", {"text": "{{ input.missing }}"})
    run = execute_run(repos, queue("action", action.id).id)
    assert run.status == "failed" and "input.missing" in run.error
    assert fake.calls == []


def test_missing_required_param_fails(repos, fake, make_action, queue):
    run = execute_run(repos, queue("action", make_action("needs").id).id)
    assert run.status == "failed" and "x" in run.error
    assert fake.calls == []


def test_unknown_operation_fails(repos, fake, make_action, queue):
    run = execute_run(repos, queue("action", make_action("nope").id).id)
    assert run.status == "failed" and "nope" in run.error


def test_unknown_connector_fails(repos, fake, make_connection, make_action, queue):
    action = make_action("echo", connection_id=make_connection(connector="ghost").id)
    run = execute_run(repos, queue("action", action.id).id)
    assert run.status == "failed" and "ghost" in run.error


def test_missing_action_fails(repos, fake, queue):
    run = execute_run(repos, queue("action", "nope").id)
    assert run.status == "failed" and "action 'nope' not found" in run.error
    assert run.tasks[0].status == "failed"


def test_missing_connection_fails(repos, fake, make_action, queue):
    run = execute_run(repos, queue("action", make_action(connection_id="gone").id).id)
    assert run.status == "failed" and "connection 'gone' not found" in run.error


def test_action_of_another_workspace_is_not_found(repos, fake, make_action, queue):
    action = make_action("echo", workspace_id="other")
    run = execute_run(repos, queue("action", action.id).id)
    assert run.status == "failed" and "not found" in run.error
    assert fake.calls == []


def test_connection_of_another_workspace_is_not_found(
    repos, fake, make_connection, make_action, queue
):
    action = make_action("echo", connection_id=make_connection(workspace_id="other").id)
    run = execute_run(repos, queue("action", action.id).id)
    assert run.status == "failed" and "connection" in run.error
    assert fake.calls == []


def test_undecryptable_secrets_fail_clearly(repos, fake, make_connection, make_action, queue):
    other = Settings(secret_key="a-completely-different-secret-key-value")
    connection = make_connection(secrets_enc=encrypt_secrets({"token": "t"}, other))
    run = execute_run(repos, queue("action", make_action(connection_id=connection.id).id).id)
    assert run.status == "failed" and "decrypt" in run.error
    assert fake.calls == []


def test_non_json_output_is_made_serialisable(repos, fake, make_action, queue):
    run = execute_run(repos, queue("action", make_action("bad_output").id).id)
    assert run.status == "succeeded"
    assert isinstance(run.output["when"], str)


def test_sync_operation_writes_company_graph(repos, store, fake, make_action, queue, ws):
    run = execute_run(repos, queue("action", make_action("sync").id).id)

    assert run.status == "succeeded"
    assert run.output == {"synced": 2, "graph": {"nodes": 2, "edges": 1, "skipped": 0}}
    graph = repos.company_graph(ws)
    [person] = store.find_nodes(graph, "Person")
    assert person.props["name"] == "Ada" and person.props["source"] == "fake"
    [team] = store.neighbors(graph, person.id, "MEMBER_OF", "out")
    assert team.props["key"] == "fake:team:core"
    assert store.find_nodes(repos.graph, "Person") == []


def test_finished_run_is_not_executed_again(repos, fake, make_action, queue):
    queued = queue("action", make_action("echo").id)
    first = execute_run(repos, queued.id)
    assert execute_run(repos, queued.id) == first
    assert len(fake.calls) == 1


def test_unknown_run_raises(repos, fake):
    with pytest.raises(LookupError):
        execute_run(repos, "nope")


def test_crash_outside_a_task_does_not_leave_run_running(
    repos, fake, make_action, queue, monkeypatch
):
    import anexa.engine.executor as executor

    def explode(*args, **kwargs):
        raise RuntimeError("store hiccup")

    monkeypatch.setattr(executor, "_context", explode)
    run = execute_run(repos, queue("action", make_action("echo").id).id)
    assert run.status == "failed" and run.error == "RuntimeError: store hiccup"
    assert run.finished_at


# --- operator runs -----------------------------------------------------------


def test_operator_chains_outputs_between_tasks(repos, fake, make_action, make_operator, queue):
    first = make_action("echo", {"items": ["a", "b"], "who": "{{ input.who }}"}, name="First")
    second = make_action("echo", {"static": 1}, name="Second")
    operator = make_operator(
        [
            task("find", first),
            task(
                "post",
                second,
                params={
                    "all": "{{ tasks.find.output.params.items }}",
                    "text": "first={{ tasks.find.output.params.items.0 }} by {{ input.who }}",
                    "prev": "{{ tasks.find.status }}",
                },
            ),
        ]
    )

    run = execute_run(repos, queue("operator", operator.id, {"who": "ann"}).id)

    assert run.status == "succeeded" and run.error is None
    assert [(t.key, t.status, t.action_name) for t in run.tasks] == [
        ("find", "succeeded", "First"),
        ("post", "succeeded", "Second"),
    ]
    assert run.tasks[1].output["params"] == {
        "static": 1,
        "all": ["a", "b"],
        "text": "first=a by ann",
        "prev": "succeeded",
    }
    assert run.output == {"find": run.tasks[0].output, "post": run.tasks[1].output}


def test_task_params_override_action_params(repos, fake, make_action, make_operator, queue):
    action = make_action("echo", {"a": 1, "b": 2})
    operator = make_operator([task("t", action, params={"b": 3})])
    run = execute_run(repos, queue("operator", operator.id).id)
    assert run.tasks[0].output["params"] == {"a": 1, "b": 3}


def test_failed_task_skips_the_rest(repos, fake, make_action, make_operator, queue):
    operator = make_operator(
        [
            task("a", make_action("echo")),
            task("b", make_action("fail")),
            task("c", make_action("echo")),
        ]
    )
    run = execute_run(repos, queue("operator", operator.id).id)

    assert run.status == "failed"
    assert run.error == "task 'b' failed: upstream said no"
    assert [t.status for t in run.tasks] == ["succeeded", "failed", "skipped"]
    assert run.tasks[2].started_at is None
    assert list(run.output) == ["a"]
    assert [op for op, _, _ in fake.calls] == ["echo", "fail"]


def test_continue_on_error_keeps_going(repos, fake, make_action, make_operator, queue):
    operator = make_operator(
        [
            task("a", make_action("fail"), continue_on_error=True),
            task("b", make_action("echo", {"prev": "{{ tasks.a.status }}"})),
        ]
    )
    run = execute_run(repos, queue("operator", operator.id).id)

    assert run.status == "succeeded" and run.error is None
    assert [t.status for t in run.tasks] == ["failed", "succeeded"]
    assert run.tasks[0].error == "upstream said no"
    assert run.tasks[1].output["params"] == {"prev": "failed"}
    assert list(run.output) == ["b"]


def test_reference_to_later_task_fails(repos, fake, make_action, make_operator, queue):
    operator = make_operator(
        [
            task("a", make_action("echo", {"x": "{{ tasks.b.output }}"})),
            task("b", make_action("echo")),
        ]
    )
    run = execute_run(repos, queue("operator", operator.id).id)
    assert run.status == "failed" and "tasks.b.output" in run.error
    assert [t.status for t in run.tasks] == ["failed", "skipped"]


def test_operator_with_missing_action_fails_that_task(
    repos, fake, make_action, make_operator, queue
):
    operator = make_operator(
        [task("a", make_action("echo")), OperatorTask(key="b", action_id="gone")]
    )
    run = execute_run(repos, queue("operator", operator.id).id)
    assert run.status == "failed" and "action 'gone' not found" in run.error
    assert [t.status for t in run.tasks] == ["succeeded", "failed"]


def test_disabled_operator_fails_without_running(repos, fake, make_action, make_operator, queue):
    operator = make_operator([task("a", make_action("echo"))], enabled=False)
    run = execute_run(repos, queue("operator", operator.id).id)
    assert run.status == "failed" and run.error == "operator is disabled"
    assert [t.status for t in run.tasks] == ["skipped"]
    assert fake.calls == []


def test_missing_operator_fails(repos, fake, queue):
    run = execute_run(repos, queue("operator", "nope").id)
    assert run.status == "failed" and "operator 'nope' not found" in run.error


def test_operator_of_another_workspace_is_not_found(repos, fake, make_action, make_operator, queue):
    operator = make_operator([task("a", make_action("echo"))])
    run = execute_run(repos, queue("operator", operator.id, workspace_id="other").id)
    assert run.status == "failed" and "not found" in run.error
    assert fake.calls == []


def test_empty_operator_succeeds(repos, fake, make_operator, queue):
    run = execute_run(repos, queue("operator", make_operator([]).id).id)
    assert run.status == "succeeded" and run.output == {} and run.tasks == []


def test_progress_is_persisted_while_running(repos, fake, make_action, make_operator, queue):
    """The second task can observe the first one finished and itself running."""
    operator = make_operator([task("a", make_action("echo")), task("b", make_action("echo"))])
    queued = queue("operator", operator.id)
    seen = []
    original = fake.execute

    def spy(operation, params, ctx):
        stored = repos.runs.get(queued.id)
        seen.append((stored.status, [t.status for t in stored.tasks]))
        return original(operation, params, ctx)

    fake.execute = spy
    execute_run(repos, queued.id)
    assert seen == [("running", ["running", "pending"]), ("running", ["succeeded", "running"])]
