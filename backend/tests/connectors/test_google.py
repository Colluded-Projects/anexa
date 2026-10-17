import json
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from orgraph.connectors.base import ConnectorError
from orgraph.connectors.google import GoogleConnector, document_text
from orgraph.graph.ontology import EDGE_TYPES, NODE_LABELS

DRIVE = "https://www.googleapis.com/drive/v3"
DOCS = "https://docs.googleapis.com/v1"
TOKEN_URI = "https://oauth2.googleapis.com/token"
google = GoogleConnector()


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def service_account(rsa_key):
    pem = rsa_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return {
        "type": "service_account",
        "client_email": "orgraph@acme.iam.gserviceaccount.com",
        "private_key_id": "key-1",
        "private_key": pem,
        "token_uri": TOKEN_URI,
    }


@pytest.fixture
def ctx(make_ctx):
    return make_ctx(secrets={"access_token": "ya29.direct"})


def drive_file(id, owners=(), **extra):
    return {
        "id": id,
        "name": f"Doc {id}",
        "mimeType": "application/vnd.google-apps.document",
        "webViewLink": f"https://docs.google.com/document/d/{id}/edit",
        "createdTime": "2026-01-01T00:00:00Z",
        "modifiedTime": "2026-01-05T00:00:00Z",
        "owners": list(owners),
        **extra,
    }


def test_spec_is_complete():
    ops = {op.name: op.kind for op in google.spec.operations}
    assert ops == {
        "list_files": "action",
        "get_document": "action",
        "create_document": "action",
        "append_text": "action",
        "sync_docs": "sync",
    }
    fields = {f.name: f for f in google.spec.config_fields}
    assert fields["service_account_json"].secret and fields["access_token"].secret
    assert not fields["subject"].secret


def test_service_account_grant_signs_a_jwt_and_caches_the_token(
    make_ctx, respx_mock, service_account, rsa_key
):
    ctx = make_ctx(
        config={"subject": "ada@acme.com"},
        secrets={"service_account_json": json.dumps(service_account)},
    )
    token_route = respx_mock.post(TOKEN_URI).respond(
        json={"access_token": "ya29.minted", "expires_in": 3599, "token_type": "Bearer"}
    )
    about = respx_mock.get(f"{DRIVE}/about").respond(
        json={"user": {"displayName": "Ada", "emailAddress": "ada@acme.com"}}
    )

    assert google.test(ctx) == {"name": "Ada", "email": "ada@acme.com"}
    assert google.test(ctx) == {"name": "Ada", "email": "ada@acme.com"}

    assert token_route.call_count == 1  # second call reuses the cached token
    assert about.calls.last.request.headers["authorization"] == "Bearer ya29.minted"

    form = parse_qs(token_route.calls.last.request.content.decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assertion = form["assertion"][0]
    assert jwt.get_unverified_header(assertion) == {"alg": "RS256", "typ": "JWT", "kid": "key-1"}
    claims = jwt.decode(
        assertion, rsa_key.public_key(), algorithms=["RS256"], audience=TOKEN_URI
    )
    assert claims["iss"] == "orgraph@acme.iam.gserviceaccount.com"
    assert claims["sub"] == "ada@acme.com"
    assert "auth/drive" in claims["scope"] and "auth/documents" in claims["scope"]
    assert claims["exp"] - claims["iat"] == 3600


def test_service_account_can_be_given_as_a_dict_without_subject(
    make_ctx, respx_mock, service_account, rsa_key
):
    ctx = make_ctx(secrets={"service_account_json": service_account})
    token_route = respx_mock.post(TOKEN_URI).respond(json={"access_token": "t"})
    respx_mock.get(f"{DRIVE}/about").respond(json={"user": {}})
    google.test(ctx)
    assertion = parse_qs(token_route.calls.last.request.content.decode())["assertion"][0]
    claims = jwt.decode(assertion, rsa_key.public_key(), algorithms=["RS256"], audience=TOKEN_URI)
    assert "sub" not in claims


def test_token_exchange_failure(make_ctx, respx_mock, service_account):
    ctx = make_ctx(secrets={"service_account_json": json.dumps(service_account)})
    respx_mock.post(TOKEN_URI).respond(
        400, json={"error": "invalid_grant", "error_description": "Invalid JWT Signature."}
    )
    with pytest.raises(ConnectorError) as exc:
        google.test(ctx)
    assert "400" in str(exc.value) and "Invalid JWT Signature" in str(exc.value)
    assert "PRIVATE KEY" not in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    ["not json", json.dumps({"client_email": "x@y.z"}),
     json.dumps({"client_email": "x@y.z", "private_key": "not a pem"})],
)
def test_bad_service_account_key(make_ctx, respx_mock, bad):
    with pytest.raises(ConnectorError, match="service account"):
        google.test(make_ctx(secrets={"service_account_json": bad}))
    assert not respx_mock.calls


def test_no_credentials(make_ctx, respx_mock):
    with pytest.raises(ConnectorError, match="service account key or an access token"):
        google.test(make_ctx())
    assert not respx_mock.calls


def test_api_error_surfaces_google_message(ctx, respx_mock):
    respx_mock.get(f"{DRIVE}/about").respond(
        401, json={"error": {"code": 401, "message": "Invalid Credentials",
                             "status": "UNAUTHENTICATED"}}
    )
    with pytest.raises(ConnectorError) as exc:
        google.test(ctx)
    assert "401" in str(exc.value) and "Invalid Credentials" in str(exc.value)
    assert "ya29.direct" not in str(exc.value)


def test_list_files_paginates(ctx, respx_mock):
    route = respx_mock.get(f"{DRIVE}/files").mock(
        side_effect=[
            httpx.Response(200, json={"files": [drive_file("a")], "nextPageToken": "p2"}),
            httpx.Response(200, json={
                "files": [drive_file("b", owners=[{"emailAddress": "ada@acme.com"}])]
            }),
        ]
    )
    result = google.execute("list_files", {"query": "name contains 'plan'", "limit": 5}, ctx)

    first, second = (call.request.url.params for call in route.calls)
    assert route.calls.last.request.headers["authorization"] == "Bearer ya29.direct"
    assert first["q"] == "name contains 'plan'" and first["pageSize"] == "5"
    assert "owners(" in first["fields"] and first["supportsAllDrives"] == "true"
    assert "pageToken" not in first
    assert second["pageToken"] == "p2" and second["pageSize"] == "4"
    assert result.output["count"] == 2
    assert result.output["files"][1] == {
        "id": "b", "name": "Doc b", "mime_type": "application/vnd.google-apps.document",
        "url": "https://docs.google.com/document/d/b/edit",
        "created_at": "2026-01-01T00:00:00Z", "modified_at": "2026-01-05T00:00:00Z",
        "owners": ["ada@acme.com"],
    }


def test_list_files_without_query_sends_no_q(ctx, respx_mock):
    route = respx_mock.get(f"{DRIVE}/files").respond(json={"files": []})
    google.execute("list_files", {}, ctx)
    assert "q" not in route.calls.last.request.url.params


DOCUMENT = {
    "documentId": "doc1",
    "title": "Roadmap",
    "body": {
        "content": [
            {"sectionBreak": {}},
            {"paragraph": {"elements": [{"textRun": {"content": "Q1 "}},
                                        {"textRun": {"content": "goals\n"}}]}},
            {"table": {"tableRows": [{"tableCells": [
                {"content": [{"paragraph": {"elements": [{"textRun": {"content": "cell\n"}}]}}]},
            ]}]}},
            {"paragraph": {"elements": [{"inlineObjectElement": {}},
                                        {"textRun": {"content": "end\n"}}]}},
        ]
    },
}


def test_document_text_walks_paragraphs_and_tables():
    assert document_text(DOCUMENT) == "Q1 goals\ncell\nend\n"
    assert document_text({}) == ""


def test_get_document(ctx, respx_mock):
    respx_mock.get(f"{DOCS}/documents/doc1").respond(json=DOCUMENT)
    result = google.execute("get_document", {"document_id": "doc1"}, ctx)
    assert result.output == {
        "document_id": "doc1", "title": "Roadmap", "text": "Q1 goals\ncell\nend\n",
        "url": "https://docs.google.com/document/d/doc1/edit",
    }


def test_create_document_with_text(ctx, respx_mock):
    create = respx_mock.post(f"{DOCS}/documents").respond(
        json={"documentId": "new1", "title": "Notes"}
    )
    update = respx_mock.post(f"{DOCS}/documents/new1:batchUpdate").respond(json={"replies": [{}]})

    result = google.execute("create_document", {"title": "Notes", "text": "hello"}, ctx)

    assert json.loads(create.calls.last.request.content) == {"title": "Notes"}
    assert json.loads(update.calls.last.request.content) == {
        "requests": [{"insertText": {"endOfSegmentLocation": {}, "text": "hello"}}]
    }
    assert result.output == {
        "document_id": "new1", "title": "Notes",
        "url": "https://docs.google.com/document/d/new1/edit",
    }


def test_create_document_without_text_makes_one_call(ctx, respx_mock):
    respx_mock.post(f"{DOCS}/documents").respond(json={"documentId": "new1", "title": "Notes"})
    google.execute("create_document", {"title": "Notes"}, ctx)
    assert len(respx_mock.calls) == 1


def test_append_text(ctx, respx_mock):
    route = respx_mock.post(f"{DOCS}/documents/doc1:batchUpdate").respond(json={})
    result = google.execute("append_text", {"document_id": "doc1", "text": "more\n"}, ctx)
    assert json.loads(route.calls.last.request.content) == {
        "requests": [{"insertText": {"endOfSegmentLocation": {}, "text": "more\n"}}]
    }
    assert result.output["appended_chars"] == 5


def test_missing_required_param_and_unknown_operation(ctx, respx_mock):
    with pytest.raises(ConnectorError, match="document_id"):
        google.execute("get_document", {}, ctx)
    with pytest.raises(ConnectorError, match="no operation"):
        google.execute("delete_drive", {}, ctx)
    assert not respx_mock.calls


def test_sync_docs(ctx, respx_mock, delta_of):
    ada = {"displayName": "Ada Lovelace", "emailAddress": "Ada@Acme.com", "permissionId": "p1"}
    route = respx_mock.get(f"{DRIVE}/files").respond(json={
        "files": [drive_file("a", owners=[ada]), drive_file("b", owners=[ada]),
                  drive_file("c")],  # shared-drive file: no owners
    })
    export = respx_mock.get(url__regex=rf"{DRIVE}/files/(a|b|c)/export").mock(
        side_effect=lambda request: httpx.Response(
            200, text="Roadmap " + request.url.path.split("/")[-2] * 5000
        )
    )
    result = google.execute("sync_docs", {}, ctx)

    q = route.calls.last.request.url.params["q"]
    assert "application/vnd.google-apps.document" in q and "trashed = false" in q
    delta = delta_of(result.graph)
    assert delta.keys("Document") == ["google:file:a", "google:file:b", "google:file:c"]
    doc = delta.node("Document", "google:file:a")
    assert doc.props["name"] == "Doc a"
    assert doc.props["url"] == "https://docs.google.com/document/d/a/edit"
    assert doc.props["modified_at"] == "2026-01-05T00:00:00Z"
    assert doc.props["text"] == ("Roadmap " + "a" * 5000)[:4000]
    assert export.call_count == 3
    assert export.calls.last.request.url.params["mimeType"] == "text/plain"
    assert export.calls.last.request.headers["authorization"] == "Bearer ya29.direct"
    assert delta.keys("Person") == ["email:ada@acme.com"]
    assert delta.node("Person", "email:ada@acme.com").props == {
        "name": "Ada Lovelace", "email": "Ada@Acme.com",
    }
    assert delta.edges() == [
        ("Person", "email:ada@acme.com", "OWNS", "Document", "google:file:a"),
        ("Person", "email:ada@acme.com", "OWNS", "Document", "google:file:b"),
    ]
    assert all(n.label in NODE_LABELS for n in result.graph.nodes)
    assert all(e.type in EDGE_TYPES for e in result.graph.edges)
    assert result.output == {"documents": 3, "people": 1}


def test_sync_docs_with_custom_query(ctx, respx_mock):
    route = respx_mock.get(f"{DRIVE}/files").respond(json={"files": []})
    google.execute("sync_docs", {"query": "'folder1' in parents", "limit": 10}, ctx)
    params = route.calls.last.request.url.params
    assert params["q"] == "'folder1' in parents" and params["pageSize"] == "10"


def test_sync_docs_without_content_skips_export(ctx, respx_mock, delta_of):
    respx_mock.get(f"{DRIVE}/files").respond(json={"files": [drive_file("a")]})
    result = google.execute("sync_docs", {"include_content": False}, ctx)
    assert "text" not in delta_of(result.graph).node("Document", "google:file:a").props
    assert len(respx_mock.calls) == 1
