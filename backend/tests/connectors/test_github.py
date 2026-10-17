import json

import httpx
import pytest

from orgraph.connectors.base import ConnectorError
from orgraph.connectors.github import GitHubConnector
from orgraph.graph.ontology import EDGE_TYPES, NODE_LABELS

API = "https://api.github.com"
TOKEN = "ghp_testtoken"
github = GitHubConnector()


@pytest.fixture
def ctx(make_ctx):
    return make_ctx(config={"org": "acme"}, secrets={"token": TOKEN})


def issue(number, author="ada", assignees=(), pull=False, **extra):
    data = {
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "html_url": f"https://github.com/acme/api/issues/{number}",
        "user": {"login": author, "type": "User"},
        "assignees": [{"login": a} for a in assignees],
        "labels": [{"name": "bug"}],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
        **extra,
    }
    if pull:
        data["pull_request"] = {"url": "..."}
    return data


def test_spec_is_complete():
    ops = {op.name: op.kind for op in github.spec.operations}
    assert ops == {
        "create_issue": "action",
        "comment_on_issue": "action",
        "list_issues": "action",
        "list_pull_requests": "action",
        "get_repo": "action",
        "sync_repos": "sync",
        "sync_members": "sync",
        "sync_issues": "sync",
    }
    fields = {f.name: f for f in github.spec.config_fields}
    assert fields["token"].secret and fields["token"].required
    assert not fields["org"].secret and fields["base_url"].default == API


def test_create_issue(ctx, respx_mock):
    route = respx_mock.post(f"{API}/repos/acme/api/issues").respond(201, json=issue(7))
    result = github.execute(
        "create_issue",
        {"repo": "acme/api", "title": "Broken", "body": "It broke", "labels": "bug, p1"},
        ctx,
    )

    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["x-github-api-version"] == "2022-11-28"
    assert json.loads(request.content) == {
        "title": "Broken", "body": "It broke", "labels": ["bug", "p1"],
    }
    assert result.output["number"] == 7
    assert result.output["url"] == "https://github.com/acme/api/issues/7"
    assert result.output["repo"] == "acme/api"


def test_repo_owner_defaults_to_connection_org(ctx, respx_mock):
    route = respx_mock.post(f"{API}/repos/acme/web/issues").respond(201, json=issue(1))
    github.execute("create_issue", {"repo": "web", "title": "t"}, ctx)
    assert route.called
    assert json.loads(route.calls.last.request.content) == {"title": "t"}


def test_repo_without_owner_and_org_is_rejected(make_ctx, respx_mock):
    ctx = make_ctx(secrets={"token": TOKEN})
    with pytest.raises(ConnectorError, match="owner/name"):
        github.execute("get_repo", {"repo": "web"}, ctx)
    assert not respx_mock.calls


def test_enterprise_base_url(make_ctx, respx_mock):
    ctx = make_ctx(config={"base_url": "https://ghe.acme.com/api/v3/"}, secrets={"token": TOKEN})
    route = respx_mock.get("https://ghe.acme.com/api/v3/user").respond(
        json={"login": "ada", "name": "Ada", "id": 1}
    )
    assert github.test(ctx) == {"login": "ada", "name": "Ada", "id": 1}
    assert route.called


def test_comment_on_issue(ctx, respx_mock):
    route = respx_mock.post(f"{API}/repos/acme/api/issues/12/comments").respond(
        201, json={"id": 99, "html_url": "https://github.com/acme/api/issues/12#issuecomment-99"}
    )
    result = github.execute(
        "comment_on_issue", {"repo": "acme/api", "number": "12", "body": "done"}, ctx
    )
    assert json.loads(route.calls.last.request.content) == {"body": "done"}
    assert result.output == {
        "repo": "acme/api", "number": 12, "id": 99,
        "url": "https://github.com/acme/api/issues/12#issuecomment-99",
    }


def test_list_issues_paginates_and_drops_pull_requests(ctx, respx_mock):
    next_url = f"{API}/repositories/1/issues?state=open&per_page=100&page=2"
    first = respx_mock.get(f"{API}/repos/acme/api/issues").respond(
        json=[issue(1), issue(2, pull=True)], headers={"Link": f'<{next_url}>; rel="next"'}
    )
    second = respx_mock.get(next_url).respond(json=[issue(3, assignees=["bob"])])

    result = github.execute("list_issues", {"repo": "acme/api"}, ctx)

    params = first.calls.last.request.url.params
    assert params["state"] == "open" and params["per_page"] == "100"
    assert second.called
    assert second.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"
    assert [i["number"] for i in result.output["issues"]] == [1, 3]
    assert result.output["count"] == 2
    assert result.output["issues"][1] == {
        "number": 3, "title": "Issue 3", "state": "open",
        "url": "https://github.com/acme/api/issues/3", "author": "ada", "assignees": ["bob"],
        "labels": ["bug"], "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }


def test_pagination_is_capped(ctx, respx_mock):
    route = respx_mock.get(f"{API}/repos/acme/api/issues").respond(
        json=[issue(1)],
        headers={"Link": f'<{API}/repos/acme/api/issues?page=2>; rel="next"'},
    )
    result = github.execute("list_issues", {"repo": "acme/api"}, ctx)
    assert route.call_count == 10
    assert result.output["count"] == 10


def test_list_pull_requests(ctx, respx_mock):
    route = respx_mock.get(f"{API}/repos/acme/api/pulls").respond(
        json=[issue(5, draft=True, head={"ref": "feature"}, base={"ref": "main"})]
    )
    result = github.execute("list_pull_requests", {"repo": "acme/api", "state": "all"}, ctx)
    assert route.calls.last.request.url.params["state"] == "all"
    pull = result.output["pull_requests"][0]
    assert (pull["number"], pull["draft"], pull["head"], pull["base"]) == (5, True, "feature",
                                                                         "main")


def test_get_repo(ctx, respx_mock):
    respx_mock.get(f"{API}/repos/acme/api").respond(json={
        "full_name": "acme/api", "description": "The API", "private": True,
        "html_url": "https://github.com/acme/api", "default_branch": "main",
        "language": "Python", "stargazers_count": 3, "open_issues_count": 2,
        "pushed_at": "2026-02-01T00:00:00Z",
    })
    result = github.execute("get_repo", {"repo": "acme/api"}, ctx)
    assert result.output == {
        "full_name": "acme/api", "description": "The API", "url": "https://github.com/acme/api",
        "private": True, "archived": False, "default_branch": "main", "language": "Python",
        "stars": 3, "open_issues": 2, "pushed_at": "2026-02-01T00:00:00Z",
    }


def test_unauthorized_reports_status_and_message_without_token(ctx, respx_mock):
    respx_mock.get(f"{API}/user").respond(401, json={"message": "Bad credentials"})
    with pytest.raises(ConnectorError) as exc:
        github.test(ctx)
    assert "401" in str(exc.value) and "Bad credentials" in str(exc.value)
    assert TOKEN not in str(exc.value)


def test_validation_error_includes_provider_details(ctx, respx_mock):
    respx_mock.post(f"{API}/repos/acme/api/issues").respond(
        422, json={"message": "Validation Failed", "errors": [{"field": "title"}]}
    )
    with pytest.raises(ConnectorError, match="422.*Validation Failed"):
        github.execute("create_issue", {"repo": "acme/api", "title": "x"}, ctx)


def test_missing_required_param_and_unknown_operation(ctx, respx_mock):
    with pytest.raises(ConnectorError, match="title"):
        github.execute("create_issue", {"repo": "acme/api"}, ctx)
    with pytest.raises(ConnectorError, match="no operation"):
        github.execute("delete_everything", {}, ctx)
    assert not respx_mock.calls


def test_transport_failure(ctx, respx_mock):
    respx_mock.get(f"{API}/user").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ConnectorError, match="ReadTimeout"):
        github.test(ctx)


def test_sync_repos_for_org(ctx, respx_mock, delta_of):
    route = respx_mock.get(f"{API}/orgs/acme/repos").respond(json=[
        {"full_name": "acme/api", "html_url": "https://github.com/acme/api",
         "description": "API", "language": "Python", "private": True},
        {"full_name": "acme/web", "html_url": "https://github.com/acme/web"},
    ])
    result = github.execute("sync_repos", {}, ctx)

    assert route.calls.last.request.url.params["type"] == "all"
    delta = delta_of(result.graph)
    assert delta.keys("Project") == ["github:repo:acme/api", "github:repo:acme/web"]
    api = delta.node("Project", "github:repo:acme/api")
    assert api.props["name"] == "acme/api"
    assert api.props["url"] == "https://github.com/acme/api"
    assert api.props["language"] == "Python" and api.props["private"] is True
    assert delta.node("Team", "github:org:acme").props["url"] == "https://github.com/acme"
    assert delta.edges() == [
        ("Team", "github:org:acme", "OWNS", "Project", "github:repo:acme/api"),
        ("Team", "github:org:acme", "OWNS", "Project", "github:repo:acme/web"),
    ]
    assert result.output == {"projects": 2, "org": "acme"}


def test_sync_repos_for_user_when_no_org(make_ctx, respx_mock, delta_of):
    ctx = make_ctx(secrets={"token": TOKEN})
    route = respx_mock.get(f"{API}/user/repos").respond(
        json=[{"full_name": "ada/dotfiles", "html_url": "https://github.com/ada/dotfiles"}]
    )
    result = github.execute("sync_repos", {}, ctx)
    assert route.calls.last.request.url.params["affiliation"] == "owner"
    delta = delta_of(result.graph)
    assert delta.keys("Project") == ["github:repo:ada/dotfiles"]
    assert delta.keys("Team") == [] and delta.edges() == []


def test_sync_members_resolves_emails(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/orgs/acme/members").respond(json=[
        {"login": "ada", "html_url": "https://github.com/ada"},
        {"login": "bob", "html_url": "https://github.com/bob"},
    ])
    respx_mock.get(f"{API}/users/ada").respond(json={
        "login": "ada", "name": "Ada Lovelace", "email": "Ada@Acme.com",
        "html_url": "https://github.com/ada", "company": "Acme",
    })
    respx_mock.get(f"{API}/users/bob").respond(json={"login": "bob", "name": None, "email": None})

    result = github.execute("sync_members", {}, ctx)

    delta = delta_of(result.graph)
    assert delta.keys("Person") == ["email:ada@acme.com", "github:user:bob"]
    ada = delta.node("Person", "email:ada@acme.com")
    assert ada.props["name"] == "Ada Lovelace"
    assert ada.props["github_login"] == "ada"
    assert ada.props["url"] == "https://github.com/ada"
    bob = delta.node("Person", "github:user:bob")
    assert bob.props["name"] == "bob" and bob.props["url"] == "https://github.com/bob"
    assert delta.edges() == [
        ("Person", "email:ada@acme.com", "MEMBER_OF", "Team", "github:org:acme"),
        ("Person", "github:user:bob", "MEMBER_OF", "Team", "github:org:acme"),
    ]
    assert result.output == {"org": "acme", "people": 2}


def test_sync_members_without_email_lookup_makes_no_profile_calls(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/orgs/other/members").respond(json=[{"login": "ada"}])
    result = github.execute("sync_members", {"org": "other", "resolve_emails": False}, ctx)
    assert len(respx_mock.calls) == 1
    delta = delta_of(result.graph)
    assert delta.keys("Person") == ["github:user:ada"]
    assert delta.keys("Team") == ["github:org:other"]


def test_sync_members_needs_an_org(make_ctx, respx_mock):
    with pytest.raises(ConnectorError, match="organization"):
        github.execute("sync_members", {}, make_ctx(secrets={"token": TOKEN}))
    assert not respx_mock.calls


def test_sync_issues(ctx, respx_mock, delta_of):
    route = respx_mock.get(f"{API}/repos/acme/api/issues").respond(json=[
        issue(1, author="ada", assignees=["bob"], closed_at=None, body="Login fails on Safari"),
        issue(2, author="ada", pull=True),
        issue(3, author="dependabot[bot]", user={"login": "dependabot[bot]", "type": "Bot"}),
    ])
    profiles = respx_mock.get(url__regex=rf"{API}/users/(ada|bob)$").mock(
        side_effect=lambda request: httpx.Response(200, json={
            "login": request.url.path.rsplit("/", 1)[-1],
            "email": "ada@acme.com" if request.url.path.endswith("ada") else None,
        })
    )
    result = github.execute("sync_issues", {"repo": "acme/api"}, ctx)

    assert route.calls.last.request.url.params["state"] == "all"
    assert profiles.call_count == 2  # ada is looked up once although she appears twice
    delta = delta_of(result.graph)
    assert delta.keys("Project") == ["github:repo:acme/api"]
    assert delta.keys("Ticket") == [
        "github:issue:acme/api#1", "github:issue:acme/api#2", "github:issue:acme/api#3",
    ]
    ticket = delta.node("Ticket", "github:issue:acme/api#1")
    assert ticket.props["name"] == "acme/api#1: Issue 1"
    assert ticket.props["kind"] == "issue" and ticket.props["labels"] == ["bug"]
    assert ticket.props["url"] == "https://github.com/acme/api/issues/1"
    assert ticket.props["text"] == "Login fails on Safari"
    assert delta.node("Ticket", "github:issue:acme/api#2").props["kind"] == "pull_request"
    assert delta.keys("Person") == ["email:ada@acme.com", "github:user:bob"]
    assert delta.edges("PART_OF") == [
        ("Ticket", f"github:issue:acme/api#{n}", "PART_OF", "Project", "github:repo:acme/api")
        for n in (1, 2, 3)
    ]
    assert delta.edges("AUTHORED") == [
        ("Person", "email:ada@acme.com", "AUTHORED", "Ticket", "github:issue:acme/api#1"),
        ("Person", "email:ada@acme.com", "AUTHORED", "Ticket", "github:issue:acme/api#2"),
    ]
    assert delta.edges("ASSIGNED_TO") == [
        ("Ticket", "github:issue:acme/api#1", "ASSIGNED_TO", "Person", "github:user:bob"),
    ]
    assert all(n.label in NODE_LABELS for n in result.graph.nodes)
    assert all(e.type in EDGE_TYPES for e in result.graph.edges)
    assert result.output == {"repo": "acme/api", "tickets": 3, "people": 2}


def test_sync_issues_honours_limit(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/repos/acme/api/issues").respond(json=[issue(n) for n in range(1, 6)])
    result = github.execute(
        "sync_issues", {"repo": "acme/api", "limit": 2, "resolve_emails": False}, ctx
    )
    assert len(delta_of(result.graph).keys("Ticket")) == 2
