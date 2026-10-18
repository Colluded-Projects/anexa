from anexa.security import decrypt_secrets


def test_catalog_lists_connector_specs(client, ada):
    r = client.get("/api/connectors", headers=ada.headers)
    assert r.status_code == 200
    (spec,) = r.json()
    assert set(spec) == {"key", "title", "description", "config_fields", "operations"}
    assert spec["key"] == "fake"
    field = next(f for f in spec["config_fields"] if f["name"] == "token")
    assert set(field) == {
        "name",
        "label",
        "type",
        "required",
        "secret",
        "help",
        "default",
        "options",
        "placeholder",
    }
    assert field["secret"] is True
    ops = {op["name"]: op for op in spec["operations"]}
    assert ops["sync_all"]["kind"] == "sync" and ops["echo"]["kind"] == "action"
    assert set(ops["echo"]) == {"name", "title", "description", "kind", "params"}


def test_create_connection_hides_secrets(client, ada, make, token, repos):
    conn = make.connection(ada, secrets={"token": token, "signing_secret": "sig-value-123"})
    assert set(conn) == {
        "id",
        "name",
        "connector",
        "config",
        "secret_fields",
        "status",
        "status_detail",
        "created_at",
        "updated_at",
    }
    assert conn["config"] == {"base_url": "https://fake.example.com"}
    assert conn["secret_fields"] == ["signing_secret", "token"]
    assert conn["status"] == "untested"
    stored = repos.connections.get(conn["id"])
    assert token not in stored.secrets_enc
    assert decrypt_secrets(stored.secrets_enc)["token"] == token


def test_secret_sent_inside_config_is_moved_to_secrets(client, ada, make, token):
    conn = make.connection(
        ada, config={"base_url": "https://x.example.com", "token": token}, secrets={}
    )
    assert conn["config"] == {"base_url": "https://x.example.com"}
    assert conn["secret_fields"] == ["token"]


def test_secrets_never_leak_in_any_response(client, ada, make, token):
    conn = make.connection(ada, secrets={"token": token, "signing_secret": "sig-value-123"})
    action = make.action(ada, conn["id"])
    cid = conn["id"]
    responses = [
        client.get(f"{ada.base}/connections", headers=ada.headers),
        client.get(f"{ada.base}/connections/{cid}", headers=ada.headers),
        client.patch(
            f"{ada.base}/connections/{cid}", json={"name": "Renamed"}, headers=ada.headers
        ),
        client.patch(
            f"{ada.base}/connections/{cid}",
            json={"secrets": {"token": token}},
            headers=ada.headers,
        ),
        client.post(f"{ada.base}/connections/{cid}/test", headers=ada.headers),
        client.get(f"{ada.base}/actions", headers=ada.headers),
        client.get(f"{ada.base}/actions/{action['id']}", headers=ada.headers),
        client.post(f"{ada.base}/actions/{action['id']}/run", headers=ada.headers),
        client.get(f"{ada.base}/runs", headers=ada.headers),
        client.get(f"{ada.base}/summary", headers=ada.headers),
        client.get("/api/me", headers=ada.headers),
    ]
    for r in responses:
        assert r.status_code < 300, r.text
        assert token not in r.text
        assert "sig-value-123" not in r.text
        assert "secrets_enc" not in r.text


def test_create_connection_validation(client, ada, token):
    url = f"{ada.base}/connections"
    unknown = client.post(url, json={"name": "x", "connector": "nope"}, headers=ada.headers)
    assert unknown.status_code == 422 and "nope" in unknown.json()["detail"]
    no_secret = client.post(
        url,
        json={"name": "x", "connector": "fake", "config": {"base_url": "u"}},
        headers=ada.headers,
    )
    assert no_secret.status_code == 422 and "token" in no_secret.json()["detail"]
    no_config = client.post(
        url,
        json={"name": "x", "connector": "fake", "secrets": {"token": token}},
        headers=ada.headers,
    )
    assert no_config.status_code == 422 and "base_url" in no_config.json()["detail"]


def test_patch_merges_secrets_and_replaces_config(client, ada, make, token, repos):
    conn = make.connection(
        ada,
        config={"base_url": "https://a.example.com", "note": "first"},
        secrets={"token": token, "signing_secret": "sig"},
    )
    url = f"{ada.base}/connections/{conn['id']}"

    # secrets merge: untouched ones survive, null clears
    r = client.patch(url, json={"secrets": {"signing_secret": None}}, headers=ada.headers)
    assert r.status_code == 200 and r.json()["secret_fields"] == ["token"]
    assert r.json()["config"] == {"base_url": "https://a.example.com", "note": "first"}
    r = client.patch(url, json={"secrets": {"signing_secret": "new-sig"}}, headers=ada.headers)
    assert r.json()["secret_fields"] == ["signing_secret", "token"]
    assert decrypt_secrets(repos.connections.get(conn["id"]).secrets_enc) == {
        "token": token,
        "signing_secret": "new-sig",
    }

    # config replaces: `note` is dropped, secrets are untouched
    r = client.patch(
        url, json={"config": {"base_url": "https://b.example.com"}}, headers=ada.headers
    )
    assert r.json()["config"] == {"base_url": "https://b.example.com"}
    assert r.json()["secret_fields"] == ["signing_secret", "token"]

    # name only
    r = client.patch(url, json={"name": "Renamed"}, headers=ada.headers)
    assert r.json()["name"] == "Renamed" and r.json()["config"]["base_url"].startswith("https://b")

    # cannot clear a required secret or drop required config
    assert (
        client.patch(url, json={"secrets": {"token": None}}, headers=ada.headers).status_code == 422
    )
    assert client.patch(url, json={"config": {}}, headers=ada.headers).status_code == 422


def test_connection_test_endpoint_records_status(client, ada, make, token):
    good = make.connection(ada)
    r = client.post(f"{ada.base}/connections/{good['id']}/test", headers=ada.headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["identity"] == {"user": "bot", "base_url": "https://fake.example.com"}
    assert isinstance(r.json()["detail"], str)
    assert (
        client.get(f"{ada.base}/connections/{good['id']}", headers=ada.headers).json()["status"]
        == "ok"
    )

    bad = make.connection(ada, name="Bad", secrets={"token": "wrong-token"})
    r = client.post(f"{ada.base}/connections/{bad['id']}/test", headers=ada.headers)
    assert r.status_code == 200
    assert r.json() == {"ok": False, "detail": "token rejected", "identity": {}}
    stored = client.get(f"{ada.base}/connections/{bad['id']}", headers=ada.headers).json()
    assert stored["status"] == "error" and stored["status_detail"] == "token rejected"

    # changing credentials resets the verdict
    r = client.patch(
        f"{ada.base}/connections/{bad['id']}",
        json={"secrets": {"token": token}},
        headers=ada.headers,
    )
    assert r.json()["status"] == "untested" and r.json()["status_detail"] == ""


def test_delete_connection(client, ada, make):
    conn = make.connection(ada)
    action = make.action(ada, conn["id"])
    url = f"{ada.base}/connections/{conn['id']}"
    assert client.delete(url, headers=ada.headers).status_code == 409
    client.delete(f"{ada.base}/actions/{action['id']}", headers=ada.headers)
    assert client.delete(url, headers=ada.headers).status_code == 204
    assert client.get(url, headers=ada.headers).status_code == 404
    assert client.get(f"{ada.base}/connections", headers=ada.headers).json() == []
