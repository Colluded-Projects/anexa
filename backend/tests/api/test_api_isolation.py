"""Every workspace-scoped resource must be invisible from another workspace:
404 when addressed through the caller's own workspace, 403 through the owner's."""

import pytest

RESOURCES = ["connections", "actions", "operators", "schedules", "agents", "runs"]


@pytest.fixture
def owned(client, ada, make):
    conn = make.connection(ada)
    action = make.action(ada, conn["id"])
    op = make.operator(ada, action["id"])
    schedule = make.schedule(ada, op["id"])
    agent = make.agent(ada)
    run = client.post(f"{ada.base}/actions/{action['id']}/run", headers=ada.headers).json()
    key = make.api_key(ada)
    return {
        "connections": conn,
        "actions": action,
        "operators": op,
        "schedules": schedule,
        "agents": agent,
        "runs": run,
        "api-keys": key,
    }


@pytest.mark.parametrize("resource", RESOURCES)
def test_get_across_workspaces(client, ada, bob, owned, resource):
    rid = owned[resource]["id"]
    assert client.get(f"{ada.base}/{resource}/{rid}", headers=ada.headers).status_code == 200
    assert client.get(f"{bob.base}/{resource}/{rid}", headers=bob.headers).status_code == 404
    assert client.get(f"{ada.base}/{resource}/{rid}", headers=bob.headers).status_code == 403
    assert client.get(f"{bob.base}/{resource}", headers=bob.headers).json() == []
    assert client.get(f"{ada.base}/{resource}", headers=bob.headers).status_code == 403


@pytest.mark.parametrize("resource", ["connections", "actions", "operators", "schedules", "agents"])
def test_write_across_workspaces(client, ada, bob, owned, resource):
    rid = owned[resource]["id"]
    body = {"enabled": False} if resource == "schedules" else {"name": "pwned"}
    assert (
        client.patch(f"{bob.base}/{resource}/{rid}", json=body, headers=bob.headers).status_code
        == 404
    )
    assert client.delete(f"{bob.base}/{resource}/{rid}", headers=bob.headers).status_code == 404
    assert (
        client.patch(f"{ada.base}/{resource}/{rid}", json=body, headers=bob.headers).status_code
        == 403
    )
    assert client.delete(f"{ada.base}/{resource}/{rid}", headers=bob.headers).status_code == 403
    # untouched
    after = client.get(f"{ada.base}/{resource}/{rid}", headers=ada.headers).json()
    assert after == owned[resource]


def test_actions_across_workspaces(client, ada, bob, owned, submitted):
    before = len(submitted)
    for base, expected in ((bob.base, 404), (ada.base, 403)):
        assert (
            client.post(
                f"{base}/actions/{owned['actions']['id']}/run", headers=bob.headers
            ).status_code
            == expected
        )
        assert (
            client.post(
                f"{base}/operators/{owned['operators']['id']}/run", headers=bob.headers
            ).status_code
            == expected
        )
        assert (
            client.post(
                f"{base}/connections/{owned['connections']['id']}/test", headers=bob.headers
            ).status_code
            == expected
        )
        assert (
            client.delete(
                f"{base}/api-keys/{owned['api-keys']['id']}", headers=bob.headers
            ).status_code
            == expected
        )
    assert len(submitted) == before
    assert client.get(f"{bob.base}/api-keys", headers=bob.headers).json() == []


def test_api_key_cannot_reach_other_workspace_resources(client, ada, bob, owned, make):
    bob_key = {"X-API-Key": make.api_key(bob)["key"]}
    for resource in RESOURCES:
        rid = owned[resource]["id"]
        assert client.get(f"{bob.base}/{resource}/{rid}", headers=bob_key).status_code == 404
        assert client.get(f"{ada.base}/{resource}/{rid}", headers=bob_key).status_code == 403
    # even after bob joins ada's workspace his key stays bound to his own
    client.post(f"{ada.base}/members", json={"email": "bob@example.com"}, headers=ada.headers)
    assert client.get(f"{ada.base}/actions", headers=bob.headers).status_code == 200
    assert client.get(f"{ada.base}/actions", headers=bob_key).status_code == 403
