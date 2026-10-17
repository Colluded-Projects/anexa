def test_health_needs_no_auth(client):
    assert client.get("/api/health").json() == {"status": "ok", "store": "memory"}


def test_signup_creates_user_and_owned_workspace(client):
    r = client.post(
        "/api/auth/signup",
        json={"email": "Ada@Example.com", "password": "correct horse", "name": "Ada"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["token_type"] == "bearer" and body["access_token"]
    assert set(body["user"]) == {"id", "email", "name", "created_at"}
    assert body["user"]["email"] == "ada@example.com"
    assert set(body["workspace"]) == {"id", "name", "slug", "role", "created_at"}
    assert body["workspace"]["name"] == "Ada's workspace"
    assert body["workspace"]["slug"] == "ada-s-workspace"
    assert body["workspace"]["role"] == "owner"


def test_signup_uses_workspace_name_and_unique_slugs(signup):
    a = signup("a@example.com", workspace_name="Acme Inc")
    b = signup("b@example.com", workspace_name="Acme Inc")
    assert a.body["workspace"]["slug"] == "acme-inc"
    assert b.body["workspace"]["slug"] == "acme-inc-2"


def test_signup_duplicate_email_is_409(client, ada):
    r = client.post(
        "/api/auth/signup",
        json={"email": "ADA@example.com", "password": "another pass", "name": "Imposter"},
    )
    assert r.status_code == 409
    assert isinstance(r.json()["detail"], str)


def test_signup_validation(client):
    short = client.post(
        "/api/auth/signup", json={"email": "x@example.com", "password": "short", "name": "X"}
    )
    assert short.status_code == 422
    bad_email = client.post(
        "/api/auth/signup", json={"email": "nope", "password": "long enough", "name": "X"}
    )
    assert bad_email.status_code == 422


def test_login(client, ada):
    r = client.post(
        "/api/auth/login", json={"email": "ADA@example.com", "password": "correct horse"}
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"access_token", "token_type", "user"}
    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["user"]["id"] == ada.user["id"]


def test_login_wrong_credentials_is_401(client, ada):
    for payload in (
        {"email": "ada@example.com", "password": "wrong password"},
        {"email": "nobody@example.com", "password": "correct horse"},
    ):
        r = client.post("/api/auth/login", json=payload)
        assert r.status_code == 401
        assert r.json() == {"detail": "incorrect email or password"}


def test_me_lists_workspaces(client, ada):
    r = client.get("/api/me", headers=ada.headers)
    assert r.status_code == 200
    assert r.json()["user"] == ada.user
    assert [w["id"] for w in r.json()["workspaces"]] == [ada.ws]
    assert "password_hash" not in r.text


def test_missing_or_bad_credentials_are_401(client, ada):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert client.get("/api/me", headers={"X-API-Key": "ogk_nope"}).status_code == 401
    assert client.get("/api/connectors").status_code == 401
    assert client.get(f"{ada.base}/actions").status_code == 401
    assert client.get("/api/me").json() == {"detail": "not authenticated"}
