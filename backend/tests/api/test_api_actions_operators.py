def test_action_crud(client, ada, make):
    conn = make.connection(ada)
    action = make.action(ada, conn["id"], description="greets")
    assert set(action) == {
        "id",
        "name",
        "description",
        "connection_id",
        "connection_name",
        "connector",
        "operation",
        "params",
        "created_at",
        "updated_at",
    }
    assert action["connection_name"] == "Eng Fake" and action["connector"] == "fake"
    assert action["params"] == {"text": "hi {{ input.who }}"}

    url = f"{ada.base}/actions/{action['id']}"
    assert client.get(url, headers=ada.headers).json() == action
    assert client.get(f"{ada.base}/actions", headers=ada.headers).json() == [action]

    r = client.patch(url, json={"name": "Say bye", "params": {"text": "bye"}}, headers=ada.headers)
    assert r.status_code == 200
    assert r.json()["name"] == "Say bye" and r.json()["params"] == {"text": "bye"}
    assert r.json()["description"] == "greets" and r.json()["operation"] == "echo"

    assert client.delete(url, headers=ada.headers).status_code == 204
    assert client.get(url, headers=ada.headers).status_code == 404


def test_action_validation(client, ada, bob, make):
    conn = make.connection(ada)
    url = f"{ada.base}/actions"
    base = {"name": "x", "connection_id": conn["id"], "operation": "echo"}
    bad_op = client.post(url, json={**base, "operation": "nope"}, headers=ada.headers)
    assert bad_op.status_code == 422 and "nope" in bad_op.json()["detail"]
    bad_conn = client.post(url, json={**base, "connection_id": "missing"}, headers=ada.headers)
    assert bad_conn.status_code == 422
    # another workspace's connection is as good as missing
    foreign = make.connection(bob)
    assert (
        client.post(
            url, json={**base, "connection_id": foreign["id"]}, headers=ada.headers
        ).status_code
        == 422
    )

    action = make.action(ada, conn["id"])
    patch = client.patch(f"{url}/{action['id']}", json={"operation": "nope"}, headers=ada.headers)
    assert patch.status_code == 422
    assert (
        client.patch(
            f"{url}/{action['id']}", json={"connection_id": foreign["id"]}, headers=ada.headers
        ).status_code
        == 422
    )
    ok = client.patch(f"{url}/{action['id']}", json={"operation": "sync_all"}, headers=ada.headers)
    assert ok.status_code == 200 and ok.json()["operation"] == "sync_all"


def test_run_action(client, ada, make, submitted):
    action = make.action(ada)
    r = client.post(
        f"{ada.base}/actions/{action['id']}/run",
        json={"input": {"who": "team"}},
        headers=ada.headers,
    )
    assert r.status_code == 202
    run = r.json()
    assert set(run) == {
        "id",
        "kind",
        "target_id",
        "target_name",
        "status",
        "trigger",
        "triggered_by",
        "input",
        "output",
        "error",
        "tasks",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert run["kind"] == "action" and run["target_id"] == action["id"]
    assert run["target_name"] == "Say hi" and run["status"] == "queued"
    assert run["trigger"] == "manual" and run["triggered_by"] == ada.user["id"]
    assert run["input"] == {"who": "team"}
    assert len(submitted) == 1

    # body is optional
    assert (
        client.post(f"{ada.base}/actions/{action['id']}/run", headers=ada.headers).json()["input"]
        == {}
    )
    assert client.post(f"{ada.base}/actions/nope/run", headers=ada.headers).status_code == 404


def test_api_key_runs_are_triggered_by_mcp(client, ada, make):
    action, op = make.action(ada), make.operator(ada)
    key = {"X-API-Key": make.api_key(ada)["key"]}
    a = client.post(f"{ada.base}/actions/{action['id']}/run", headers=key)
    o = client.post(f"{ada.base}/operators/{op['id']}/run", json={"input": {"n": 1}}, headers=key)
    assert a.status_code == o.status_code == 202
    assert a.json()["trigger"] == o.json()["trigger"] == "mcp"
    assert a.json()["triggered_by"] == ada.user["id"]
    assert o.json()["kind"] == "operator" and o.json()["input"] == {"n": 1}


def test_run_reports_queue_failure_as_503(client, ada, make, monkeypatch):
    from anexa.engine import dispatch

    def boom(*args, **kwargs):
        raise ConnectionError("broker down")

    monkeypatch.setattr(dispatch, "submit_run", boom)
    r = client.post(f"{ada.base}/actions/{make.action(ada)['id']}/run", headers=ada.headers)
    assert r.status_code == 503 and "broker down" in r.json()["detail"]


def test_operator_crud(client, ada, make):
    a1 = make.action(ada)
    a2 = make.action(ada, a1["connection_id"], name="Second")
    op = make.operator(
        ada,
        tasks=[
            {"key": "find", "action_id": a1["id"]},
            {
                "key": "post",
                "action_id": a2["id"],
                "params": {"text": "{{ tasks.find.output.text }}"},
                "continue_on_error": True,
            },
        ],
        description="digest",
    )
    assert set(op) == {
        "id",
        "name",
        "description",
        "enabled",
        "tasks",
        "created_at",
        "updated_at",
    }
    assert op["enabled"] is True
    assert op["tasks"] == [
        {"key": "find", "action_id": a1["id"], "params": {}, "continue_on_error": False},
        {
            "key": "post",
            "action_id": a2["id"],
            "params": {"text": "{{ tasks.find.output.text }}"},
            "continue_on_error": True,
        },
    ]
    url = f"{ada.base}/operators/{op['id']}"
    assert client.get(url, headers=ada.headers).json() == op
    assert client.get(f"{ada.base}/operators", headers=ada.headers).json() == [op]

    r = client.patch(url, json={"enabled": False, "name": "Weekly"}, headers=ada.headers)
    assert r.json()["enabled"] is False and r.json()["name"] == "Weekly"
    assert len(r.json()["tasks"]) == 2
    r = client.patch(
        url, json={"tasks": [{"key": "only", "action_id": a2["id"]}]}, headers=ada.headers
    )
    assert [t["key"] for t in r.json()["tasks"]] == ["only"]
    assert client.get(url, headers=ada.headers).json()["tasks"] == r.json()["tasks"]

    empty = client.post(f"{ada.base}/operators", json={"name": "Empty"}, headers=ada.headers)
    assert empty.status_code == 201 and empty.json()["tasks"] == []


def test_operator_task_validation(client, ada, bob, make):
    action = make.action(ada)
    foreign = make.action(bob)
    url = f"{ada.base}/operators"

    def post(tasks):
        return client.post(url, json={"name": "x", "tasks": tasks}, headers=ada.headers)

    dupes = post([{"key": "a", "action_id": action["id"]}, {"key": "a", "action_id": action["id"]}])
    assert dupes.status_code == 422 and "duplicate" in dupes.json()["detail"]
    assert post([{"key": "1bad", "action_id": action["id"]}]).status_code == 422
    assert post([{"key": "has-dash", "action_id": action["id"]}]).status_code == 422
    assert post([{"key": "a", "action_id": "missing"}]).status_code == 422
    assert post([{"key": "a", "action_id": foreign["id"]}]).status_code == 422

    op = make.operator(ada, action["id"])
    patch = client.patch(
        f"{url}/{op['id']}",
        json={"tasks": [{"key": "a", "action_id": "missing"}]},
        headers=ada.headers,
    )
    assert patch.status_code == 422


def test_action_in_use_cannot_be_deleted(client, ada, make):
    action = make.action(ada)
    op = make.operator(ada, action["id"])
    url = f"{ada.base}/actions/{action['id']}"
    r = client.delete(url, headers=ada.headers)
    assert r.status_code == 409 and "Daily hello" in r.json()["detail"]
    client.delete(f"{ada.base}/operators/{op['id']}", headers=ada.headers)
    assert client.delete(url, headers=ada.headers).status_code == 204


def test_deleting_operator_removes_its_schedules_and_agent_links(client, ada, make):
    op = make.operator(ada)
    keep = make.operator(ada, name="Keep")
    make.schedule(ada, op["id"])
    kept_schedule = make.schedule(ada, keep["id"])
    agent = make.agent(ada, operator_ids=[op["id"], keep["id"]])

    assert client.delete(f"{ada.base}/operators/{op['id']}", headers=ada.headers).status_code == 204
    schedules = client.get(f"{ada.base}/schedules", headers=ada.headers).json()
    assert [s["id"] for s in schedules] == [kept_schedule["id"]]
    agent = client.get(f"{ada.base}/agents/{agent['id']}", headers=ada.headers).json()
    assert agent["operator_ids"] == [keep["id"]]


def test_run_operator(client, ada, make):
    op = make.operator(ada)
    r = client.post(f"{ada.base}/operators/{op['id']}/run", json={}, headers=ada.headers)
    assert r.status_code == 202
    assert r.json()["kind"] == "operator" and r.json()["target_name"] == "Daily hello"
    assert client.post(f"{ada.base}/operators/nope/run", headers=ada.headers).status_code == 404
