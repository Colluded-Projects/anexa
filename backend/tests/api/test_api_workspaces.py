def test_create_and_list_workspaces(client, ada):
    r = client.post("/api/workspaces", json={"name": "Second Team"}, headers=ada.headers)
    assert r.status_code == 201
    assert r.json()["role"] == "owner" and r.json()["slug"] == "second-team"
    listed = client.get("/api/workspaces", headers=ada.headers).json()
    assert [w["name"] for w in listed] == ["Ada's workspace", "Second Team"]


def test_non_member_gets_403_and_unknown_workspace_404(client, ada, bob):
    assert client.get(f"{ada.base}/members", headers=bob.headers).status_code == 403
    assert client.get(f"{ada.base}/summary", headers=bob.headers).status_code == 403
    assert client.get("/api/workspaces/nope/members", headers=bob.headers).status_code == 404


def test_members_lifecycle(client, ada, bob):
    r = client.post(f"{ada.base}/members", json={"email": "BOB@example.com"}, headers=ada.headers)
    assert r.status_code == 201
    assert r.json() == {
        "user_id": bob.user["id"],
        "email": "bob@example.com",
        "name": "Bob",
        "role": "member",
    }
    members = client.get(f"{ada.base}/members", headers=bob.headers).json()
    assert {(m["email"], m["role"]) for m in members} == {
        ("ada@example.com", "owner"),
        ("bob@example.com", "member"),
    }
    # bob now sees the workspace, but cannot manage members
    assert len(client.get("/api/workspaces", headers=bob.headers).json()) == 2
    forbidden = client.post(
        f"{ada.base}/members", json={"email": "ada@example.com"}, headers=bob.headers
    )
    assert forbidden.status_code == 403
    assert (
        client.delete(f"{ada.base}/members/{ada.user['id']}", headers=bob.headers).status_code
        == 403
    )

    again = client.post(
        f"{ada.base}/members", json={"email": "bob@example.com"}, headers=ada.headers
    )
    assert again.status_code == 409

    gone = client.delete(f"{ada.base}/members/{bob.user['id']}", headers=ada.headers)
    assert gone.status_code == 204 and gone.content == b""
    assert client.get(f"{ada.base}/members", headers=bob.headers).status_code == 403
    assert (
        client.delete(f"{ada.base}/members/{bob.user['id']}", headers=ada.headers).status_code
        == 404
    )


def test_add_member_unknown_email_is_404(client, ada):
    r = client.post(f"{ada.base}/members", json={"email": "ghost@example.com"}, headers=ada.headers)
    assert r.status_code == 404


def test_cannot_remove_last_owner(client, ada, bob):
    r = client.delete(f"{ada.base}/members/{ada.user['id']}", headers=ada.headers)
    assert r.status_code == 409
    # with a second owner the first can go
    client.post(
        f"{ada.base}/members",
        json={"email": "bob@example.com", "role": "owner"},
        headers=ada.headers,
    )
    assert (
        client.delete(f"{ada.base}/members/{ada.user['id']}", headers=ada.headers).status_code
        == 204
    )


def test_api_key_lifecycle(client, ada, make):
    created = make.api_key(ada, "claude code")
    assert set(created) == {"id", "name", "prefix", "created_at", "last_used_at", "key"}
    assert created["key"].startswith("ogk_") and created["key"].startswith(created["prefix"])
    assert created["last_used_at"] is None

    listed = client.get(f"{ada.base}/api-keys", headers=ada.headers)
    assert [k["id"] for k in listed.json()] == [created["id"]]
    assert "key" not in listed.json()[0] and created["key"] not in listed.text
    assert "key_hash" not in listed.text

    key_headers = {"X-API-Key": created["key"]}
    me = client.get("/api/me", headers=key_headers)
    assert me.status_code == 200 and me.json()["user"]["id"] == ada.user["id"]
    used = client.get(f"{ada.base}/api-keys", headers=ada.headers).json()[0]
    assert used["last_used_at"] is not None

    assert (
        client.delete(f"{ada.base}/api-keys/{created['id']}", headers=ada.headers).status_code
        == 204
    )
    assert client.get("/api/me", headers=key_headers).status_code == 401
    assert (
        client.delete(f"{ada.base}/api-keys/{created['id']}", headers=ada.headers).status_code
        == 404
    )


def test_api_key_is_limited_to_its_workspace(client, ada, make):
    other = client.post("/api/workspaces", json={"name": "Other"}, headers=ada.headers).json()
    key = {"X-API-Key": make.api_key(ada)["key"]}

    assert [w["id"] for w in client.get("/api/me", headers=key).json()["workspaces"]] == [ada.ws]
    assert [w["id"] for w in client.get("/api/workspaces", headers=key).json()] == [ada.ws]
    assert client.get(f"{ada.base}/actions", headers=key).status_code == 200
    # ada is an owner of `other`, but the key is not valid there
    assert client.get(f"/api/workspaces/{other['id']}/actions", headers=key).status_code == 403
    assert client.post("/api/workspaces", json={"name": "X"}, headers=key).status_code == 403


def test_api_key_dies_with_membership(client, ada, bob, make):
    client.post(f"{ada.base}/members", json={"email": "bob@example.com"}, headers=ada.headers)
    key = client.post(f"{ada.base}/api-keys", json={"name": "bob key"}, headers=bob.headers).json()
    assert client.get(f"{ada.base}/runs", headers={"X-API-Key": key["key"]}).status_code == 200
    client.delete(f"{ada.base}/members/{bob.user['id']}", headers=ada.headers)
    assert client.get(f"{ada.base}/runs", headers={"X-API-Key": key["key"]}).status_code == 401


def test_member_cannot_delete_someone_elses_key(client, ada, bob, make):
    client.post(f"{ada.base}/members", json={"email": "bob@example.com"}, headers=ada.headers)
    key = make.api_key(ada)
    r = client.delete(f"{ada.base}/api-keys/{key['id']}", headers=bob.headers)
    assert r.status_code == 403


def test_summary(client, ada, make):
    op = make.operator(ada)
    make.schedule(ada, op["id"])
    make.agent(ada)
    make.node(ada)
    make.node(ada, "Team", "Platform")
    client.post(f"{ada.base}/operators/{op['id']}/run", headers=ada.headers)

    body = client.get(f"{ada.base}/summary", headers=ada.headers).json()
    assert body["counts"] == {
        "connections": 1,
        "actions": 1,
        "operators": 1,
        "schedules": 1,
        "agents": 1,
        "runs": 1,
    }
    assert body["runs_by_status"] == {"queued": 1, "running": 0, "succeeded": 0, "failed": 0}
    assert len(body["recent_runs"]) == 1 and body["recent_runs"][0]["target_id"] == op["id"]
    assert body["graph"] == {"Person": 1, "Team": 1}
