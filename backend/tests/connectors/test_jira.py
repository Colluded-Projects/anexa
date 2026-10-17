import base64
import json

import httpx
import pytest

from orgraph.connectors.base import ConnectorError
from orgraph.connectors.jira import JiraConnector, to_adf
from orgraph.graph.ontology import EDGE_TYPES, NODE_LABELS

SITE = "https://acme.atlassian.net"
API = f"{SITE}/rest/api/3"
TOKEN = "jira-api-token"
BASIC = "Basic " + base64.b64encode(f"ada@acme.com:{TOKEN}".encode()).decode()
jira = JiraConnector()


@pytest.fixture
def ctx(make_ctx):
    return make_ctx(
        config={"base_url": SITE + "/", "email": "ada@acme.com"}, secrets={"api_token": TOKEN}
    )


def paragraph(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def raw_issue(key, assignee=None, reporter=None, project="ENG", description=None):
    return {
        "key": key,
        "fields": {
            "summary": f"Summary {key}",
            "status": {"name": "In Progress"},
            "issuetype": {"name": "Bug"},
            "priority": {"name": "High"},
            "assignee": assignee,
            "reporter": reporter,
            "project": {"key": project, "name": "Engineering", "projectTypeKey": "software"},
            "created": "2026-01-01T10:00:00.000+0000",
            "updated": "2026-01-02T10:00:00.000+0000",
            "description": description,
        },
    }


ADA = {"accountId": "a1", "displayName": "Ada Lovelace", "emailAddress": "Ada@Acme.com"}
BOB = {"accountId": "b2", "displayName": "Bob"}  # email hidden by privacy settings


def test_spec_is_complete():
    ops = {op.name: op.kind for op in jira.spec.operations}
    assert ops == {
        "create_issue": "action",
        "add_comment": "action",
        "search_issues": "action",
        "transition_issue": "action",
        "sync_projects": "sync",
        "sync_issues": "sync",
    }
    fields = {f.name: f for f in jira.spec.config_fields}
    assert fields["api_token"].secret and not fields["email"].secret
    assert all(fields[name].required for name in ("base_url", "email", "api_token"))


def test_to_adf():
    assert to_adf("one\n\ntwo") == {
        "type": "doc",
        "version": 1,
        "content": [paragraph("one"), {"type": "paragraph", "content": []}, paragraph("two")],
    }
    assert to_adf("")["content"] == [{"type": "paragraph", "content": []}]
    ready = {"type": "doc", "version": 1, "content": []}
    assert to_adf(ready) is ready


def test_create_issue_sends_adf_with_basic_auth(ctx, respx_mock):
    route = respx_mock.post(f"{API}/issue").respond(
        201, json={"id": "10001", "key": "ENG-7", "self": f"{API}/issue/10001"}
    )
    result = jira.execute(
        "create_issue",
        {"project": "ENG", "summary": "Fix login", "description": "Steps\nMore"},
        ctx,
    )

    request = route.calls.last.request
    assert request.headers["authorization"] == BASIC
    assert json.loads(request.content) == {
        "fields": {
            "project": {"key": "ENG"},
            "summary": "Fix login",
            "issuetype": {"name": "Task"},
            "description": {
                "type": "doc", "version": 1, "content": [paragraph("Steps"), paragraph("More")],
            },
        }
    }
    assert result.output == {"key": "ENG-7", "id": "10001", "url": f"{SITE}/browse/ENG-7"}


def test_create_issue_with_type_and_no_description(ctx, respx_mock):
    route = respx_mock.post(f"{API}/issue").respond(201, json={"id": "1", "key": "ENG-1"})
    jira.execute("create_issue", {"project": "ENG", "summary": "s", "issue_type": "Bug"}, ctx)
    fields = json.loads(route.calls.last.request.content)["fields"]
    assert fields["issuetype"] == {"name": "Bug"} and "description" not in fields


def test_add_comment(ctx, respx_mock):
    route = respx_mock.post(f"{API}/issue/ENG-7/comment").respond(201, json={"id": "500"})
    result = jira.execute("add_comment", {"issue": "ENG-7", "body": "Shipped"}, ctx)
    assert json.loads(route.calls.last.request.content) == {
        "body": {"type": "doc", "version": 1, "content": [paragraph("Shipped")]}
    }
    assert result.output == {"issue": "ENG-7", "id": "500", "url": f"{SITE}/browse/ENG-7"}


def test_search_issues_follows_next_page_token(ctx, respx_mock):
    route = respx_mock.post(f"{API}/search/jql").mock(
        side_effect=[
            httpx.Response(200, json={"issues": [raw_issue("ENG-1", assignee=ADA)],
                                      "nextPageToken": "tok2", "isLast": False}),
            httpx.Response(200, json={"issues": [raw_issue("ENG-2")], "isLast": True}),
        ]
    )
    result = jira.execute("search_issues", {"jql": "project = ENG", "limit": "10"}, ctx)

    first, second = (json.loads(call.request.content) for call in route.calls)
    assert first["jql"] == "project = ENG" and first["maxResults"] == 10
    assert "summary" in first["fields"] and "nextPageToken" not in first
    assert second["nextPageToken"] == "tok2" and second["maxResults"] == 9
    assert result.output["count"] == 2
    assert result.output["issues"][0] == {
        "key": "ENG-1", "summary": "Summary ENG-1", "status": "In Progress", "type": "Bug",
        "priority": "High", "assignee": "Ada Lovelace", "reporter": None, "project": "ENG",
        "created_at": "2026-01-01T10:00:00.000+0000",
        "updated_at": "2026-01-02T10:00:00.000+0000", "url": f"{SITE}/browse/ENG-1",
    }


def test_search_stops_at_limit(ctx, respx_mock):
    route = respx_mock.post(f"{API}/search/jql").respond(
        json={"issues": [raw_issue("ENG-1"), raw_issue("ENG-2")], "nextPageToken": "more"}
    )
    result = jira.execute("search_issues", {"jql": "x", "limit": 2}, ctx)
    assert route.call_count == 1 and result.output["count"] == 2


def test_transition_issue_by_name(ctx, respx_mock):
    respx_mock.get(f"{API}/issue/ENG-7/transitions").respond(json={
        "transitions": [
            {"id": "11", "name": "Start work", "to": {"name": "In Progress"}},
            {"id": "31", "name": "Resolve", "to": {"name": "Done"}},
        ]
    })
    post = respx_mock.post(f"{API}/issue/ENG-7/transitions").respond(204)

    result = jira.execute("transition_issue", {"issue": "ENG-7", "transition": "done"}, ctx)

    assert json.loads(post.calls.last.request.content) == {"transition": {"id": "31"}}
    assert result.output == {
        "issue": "ENG-7", "transition": "Resolve", "status": "Done",
        "url": f"{SITE}/browse/ENG-7",
    }


def test_transition_issue_unknown_lists_available(ctx, respx_mock):
    respx_mock.get(f"{API}/issue/ENG-7/transitions").respond(
        json={"transitions": [{"id": "11", "name": "Start work", "to": {"name": "In Progress"}}]}
    )
    with pytest.raises(ConnectorError, match="no transition 'Ship'.*Start work"):
        jira.execute("transition_issue", {"issue": "ENG-7", "transition": "Ship"}, ctx)
    assert len(respx_mock.calls) == 1  # nothing was posted


def test_unauthorized(ctx, respx_mock):
    respx_mock.get(f"{API}/myself").respond(401, text="Client must be authenticated")
    with pytest.raises(ConnectorError) as exc:
        jira.test(ctx)
    assert "401" in str(exc.value) and "authenticated" in str(exc.value)
    assert TOKEN not in str(exc.value) and BASIC not in str(exc.value)


def test_error_messages_from_jira_are_surfaced(ctx, respx_mock):
    respx_mock.post(f"{API}/issue").respond(
        400, json={"errorMessages": [], "errors": {"project": "project is required"}}
    )
    with pytest.raises(ConnectorError, match="400.*project is required"):
        jira.execute("create_issue", {"project": "NOPE", "summary": "s"}, ctx)


def test_test_returns_identity(ctx, respx_mock):
    route = respx_mock.get(f"{API}/myself").respond(json=ADA)
    assert jira.test(ctx) == {
        "account_id": "a1", "name": "Ada Lovelace", "email": "Ada@Acme.com",
    }
    assert route.calls.last.request.headers["authorization"] == BASIC


def test_missing_connection_fields(make_ctx, respx_mock):
    with pytest.raises(ConnectorError, match="base_url"):
        jira.test(make_ctx(config={"email": "a@b.c"}, secrets={"api_token": "t"}))
    with pytest.raises(ConnectorError, match="api_token"):
        jira.test(make_ctx(config={"base_url": SITE, "email": "a@b.c"}))
    assert not respx_mock.calls


def test_missing_required_param_and_unknown_operation(ctx, respx_mock):
    with pytest.raises(ConnectorError, match="summary"):
        jira.execute("create_issue", {"project": "ENG"}, ctx)
    with pytest.raises(ConnectorError, match="no operation"):
        jira.execute("delete_project", {}, ctx)
    assert not respx_mock.calls


def test_sync_projects_paginates(ctx, respx_mock, delta_of):
    route = respx_mock.get(f"{API}/project/search").mock(
        side_effect=[
            httpx.Response(200, json={
                "isLast": False,
                "values": [{"key": "ENG", "name": "Engineering", "projectTypeKey": "software",
                            "lead": BOB}],
            }),
            httpx.Response(200, json={"isLast": True, "values": [{"key": "OPS", "name": "Ops"}]}),
        ]
    )
    result = jira.execute("sync_projects", {}, ctx)

    first, second = (call.request.url.params for call in route.calls)
    assert first["startAt"] == "0" and first["expand"] == "lead"
    assert second["startAt"] == "1"
    delta = delta_of(result.graph)
    assert delta.keys("Project") == ["jira:project:ENG", "jira:project:OPS"]
    eng = delta.node("Project", "jira:project:ENG")
    assert eng.props["name"] == "Engineering"
    assert eng.props["url"] == f"{SITE}/browse/ENG"
    assert eng.props["project_type"] == "software"
    assert delta.node("Person", "jira:user:b2").props["name"] == "Bob"
    assert delta.edges() == [("Person", "jira:user:b2", "OWNS", "Project", "jira:project:ENG")]
    assert result.output == {"projects": 2, "people": 1}


def test_sync_issues_by_project(ctx, respx_mock, delta_of):
    route = respx_mock.post(f"{API}/search/jql").respond(json={
        "isLast": True,
        "issues": [raw_issue("ENG-1", assignee=ADA, reporter=BOB,
                             description={"type": "doc", "content": [
                                 paragraph("Steps to reproduce"),
                                 {"type": "bulletList", "content": [
                                     {"type": "listItem",
                                      "content": [paragraph("Open the login page")]}]}]}),
                   raw_issue("ENG-2", reporter=ADA, description="plain description")],
    })
    result = jira.execute("sync_issues", {"project": "ENG"}, ctx)

    sent = json.loads(route.calls.last.request.content)
    assert sent["jql"] == 'project = "ENG" ORDER BY updated DESC'
    assert "description" in sent["fields"]
    delta = delta_of(result.graph)
    assert delta.keys("Ticket") == ["jira:issue:ENG-1", "jira:issue:ENG-2"]
    ticket = delta.node("Ticket", "jira:issue:ENG-1")
    assert ticket.props["name"] == "ENG-1: Summary ENG-1"
    assert ticket.props["state"] == "In Progress" and ticket.props["kind"] == "Bug"
    assert ticket.props["url"] == f"{SITE}/browse/ENG-1"
    assert ticket.props["text"] == "Steps to reproduce Open the login page"
    assert delta.node("Ticket", "jira:issue:ENG-2").props["text"] == "plain description"
    assert delta.keys("Project") == ["jira:project:ENG"]
    assert delta.keys("Person") == ["email:ada@acme.com", "jira:user:b2"]
    assert delta.edges("PART_OF") == [
        ("Ticket", "jira:issue:ENG-1", "PART_OF", "Project", "jira:project:ENG"),
        ("Ticket", "jira:issue:ENG-2", "PART_OF", "Project", "jira:project:ENG"),
    ]
    assert delta.edges("ASSIGNED_TO") == [
        ("Ticket", "jira:issue:ENG-1", "ASSIGNED_TO", "Person", "email:ada@acme.com"),
    ]
    assert delta.edges("AUTHORED") == [
        ("Person", "email:ada@acme.com", "AUTHORED", "Ticket", "jira:issue:ENG-2"),
        ("Person", "jira:user:b2", "AUTHORED", "Ticket", "jira:issue:ENG-1"),
    ]
    assert all(n.label in NODE_LABELS for n in result.graph.nodes)
    assert all(e.type in EDGE_TYPES for e in result.graph.edges)
    assert result.output["tickets"] == 2 and result.output["people"] == 2


def test_sync_issues_prefers_jql_and_requires_a_filter(ctx, respx_mock):
    route = respx_mock.post(f"{API}/search/jql").respond(json={"issues": []})
    jira.execute("sync_issues", {"project": "ENG", "jql": "assignee = currentUser()"}, ctx)
    assert json.loads(route.calls.last.request.content)["jql"] == "assignee = currentUser()"

    with pytest.raises(ConnectorError, match="project key or a JQL"):
        jira.execute("sync_issues", {}, ctx)
    assert route.call_count == 1
