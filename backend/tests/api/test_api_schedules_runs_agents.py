from anexa.models import Run


def test_schedule_crud(client, ada, make):
    op = make.operator(ada)
    s = make.schedule(ada, op["id"], cron="30 8 * * 1-5", timezone="Europe/Berlin", input={"a": 1})
    assert set(s) == {
        "id",
        "operator_id",
        "operator_name",
        "cron",
        "timezone",
        "enabled",
        "input",
        "next_run_at",
        "last_run_at",
        "created_at",
        "updated_at",
    }
    assert s["operator_name"] == "Daily hello" and s["enabled"] is True
    assert s["next_run_at"] > s["created_at"] and s["last_run_at"] is None
    assert s["input"] == {"a": 1}

    url = f"{ada.base}/schedules/{s['id']}"
    assert client.get(url, headers=ada.headers).json() == s

    disabled = client.patch(url, json={"enabled": False}, headers=ada.headers).json()
    assert disabled["enabled"] is False and disabled["next_run_at"] is None
    enabled = client.patch(url, json={"enabled": True}, headers=ada.headers).json()
    assert enabled["next_run_at"] == s["next_run_at"]

    changed = client.patch(url, json={"cron": "0 0 1 1 *", "timezone": "UTC"}, headers=ada.headers)
    assert changed.status_code == 200
    assert changed.json()["cron"] == "0 0 1 1 *"
    assert changed.json()["next_run_at"] != s["next_run_at"]
    assert changed.json()["next_run_at"][4:] == "-01-01T00:00:00.000Z"

    assert client.delete(url, headers=ada.headers).status_code == 204
    assert client.get(url, headers=ada.headers).status_code == 404


def test_schedule_validation(client, ada, bob, make):
    op = make.operator(ada)
    url = f"{ada.base}/schedules"

    def post(**over):
        return client.post(
            url, json={"operator_id": op["id"], "cron": "* * * * *", **over}, headers=ada.headers
        )

    assert post(cron="not a cron").status_code == 422
    assert post(cron="* * * * * *").status_code == 422
    assert post(cron="61 * * * *").status_code == 422
    assert post(timezone="Mars/Olympus").status_code == 422
    assert post(operator_id="missing").status_code == 422
    assert post(operator_id=make.operator(bob)["id"]).status_code == 422
    assert isinstance(post(cron="nope").json()["detail"], str)

    s = post().json()
    assert (
        client.patch(f"{url}/{s['id']}", json={"cron": "bad"}, headers=ada.headers).status_code
        == 422
    )
    assert (
        client.patch(
            f"{url}/{s['id']}", json={"timezone": "Nope/Zone"}, headers=ada.headers
        ).status_code
        == 422
    )


def test_schedules_filter_by_operator(client, ada, make):
    op1, op2 = make.operator(ada), make.operator(ada, name="Other")
    s1 = make.schedule(ada, op1["id"])
    make.schedule(ada, op2["id"])
    assert len(client.get(f"{ada.base}/schedules", headers=ada.headers).json()) == 2
    only = client.get(f"{ada.base}/schedules?operator_id={op1['id']}", headers=ada.headers).json()
    assert [s["id"] for s in only] == [s1["id"]]


def test_runs_list_filters_and_detail(client, ada, make, repos):
    action, op = make.action(ada), make.operator(ada)
    first = client.post(f"{ada.base}/actions/{action['id']}/run", headers=ada.headers).json()
    client.post(f"{ada.base}/operators/{op['id']}/run", headers=ada.headers)
    last = client.post(f"{ada.base}/operators/{op['id']}/run", headers=ada.headers).json()
    repos.runs.update(
        last["id"],
        status="failed",
        error="boom",
        tasks=[{"key": "greet", "action_id": action["id"], "status": "failed", "error": "boom"}],
    )

    def runs(query=""):
        r = client.get(f"{ada.base}/runs{query}", headers=ada.headers)
        assert r.status_code == 200
        return r.json()

    assert len(runs()) == 3
    assert [r["created_at"] for r in runs()] == sorted(
        (r["created_at"] for r in runs()), reverse=True
    )
    assert [r["id"] for r in runs("?kind=action")] == [first["id"]]
    assert len(runs(f"?target_id={op['id']}")) == 2
    assert [r["id"] for r in runs("?status=failed")] == [last["id"]]
    assert len(runs("?kind=operator&status=queued")) == 1
    assert len(runs("?limit=2")) == 2
    assert client.get(f"{ada.base}/runs?limit=500", headers=ada.headers).status_code == 422
    assert client.get(f"{ada.base}/runs?status=bogus", headers=ada.headers).status_code == 422

    detail = client.get(f"{ada.base}/runs/{last['id']}", headers=ada.headers).json()
    assert detail["status"] == "failed" and detail["error"] == "boom"
    assert detail["tasks"] == [
        {
            "key": "greet",
            "action_id": action["id"],
            "action_name": "",
            "status": "failed",
            "output": None,
            "error": "boom",
            "started_at": None,
            "finished_at": None,
        }
    ]
    assert client.get(f"{ada.base}/runs/nope", headers=ada.headers).status_code == 404


def test_agent_crud(client, ada, bob, make):
    action, op = make.action(ada), make.operator(ada)
    agent = make.agent(
        ada,
        provider="jev",
        model="jev-1",
        instructions="decide",
        action_ids=[action["id"]],
        operator_ids=[op["id"]],
    )
    assert set(agent) == {
        "id",
        "name",
        "description",
        "provider",
        "model",
        "instructions",
        "action_ids",
        "operator_ids",
        "status",
        "created_at",
        "updated_at",
    }
    assert agent["status"] == "not_connected" and agent["provider"] == "jev"
    assert agent["action_ids"] == [action["id"]] and agent["operator_ids"] == [op["id"]]
    assert make.agent(ada, name="Default")["provider"] == "claude_code"

    url = f"{ada.base}/agents/{agent['id']}"
    assert client.get(url, headers=ada.headers).json() == agent
    assert len(client.get(f"{ada.base}/agents", headers=ada.headers).json()) == 2

    r = client.patch(url, json={"name": "Renamed", "action_ids": []}, headers=ada.headers)
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed" and r.json()["action_ids"] == []
    assert r.json()["operator_ids"] == [op["id"]] and r.json()["status"] == "not_connected"

    # status cannot be set, links must exist in this workspace, provider is an enum
    assert (
        client.patch(url, json={"action_ids": ["missing"]}, headers=ada.headers).status_code == 422
    )
    assert (
        client.patch(
            url, json={"operator_ids": [make.operator(bob)["id"]]}, headers=ada.headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{ada.base}/agents", json={"name": "x", "action_ids": ["missing"]}, headers=ada.headers
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{ada.base}/agents", json={"name": "x", "provider": "skynet"}, headers=ada.headers
        ).status_code
        == 422
    )

    assert client.delete(url, headers=ada.headers).status_code == 204
    assert client.get(url, headers=ada.headers).status_code == 404


def test_deleting_action_unlinks_it_from_agents(client, ada, make):
    action = make.action(ada)
    agent = make.agent(ada, action_ids=[action["id"]])
    client.delete(f"{ada.base}/actions/{action['id']}", headers=ada.headers)
    assert (
        client.get(f"{ada.base}/agents/{agent['id']}", headers=ada.headers).json()["action_ids"]
        == []
    )


def test_run_model_fields_not_in_contract_are_hidden(client, ada, make, repos):
    action = make.action(ada)
    repos.runs.create(Run(workspace_id=ada.ws, kind="action", target_id=action["id"]))
    (run,) = client.get(f"{ada.base}/runs", headers=ada.headers).json()
    assert "workspace_id" not in run
