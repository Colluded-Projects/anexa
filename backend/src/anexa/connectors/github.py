from __future__ import annotations

from typing import Any

from ..graph.ontology import TEXT_PROP, entity_key, person_key
from . import register
from ._http import as_bool, as_int, as_list, json_body, require, send
from .base import (
    Connector,
    ConnectorContext,
    ConnectorError,
    ConnectorSpec,
    EdgeUpsert,
    FieldSpec,
    GraphDelta,
    NodeUpsert,
    OperationResult,
    OperationSpec,
)

DEFAULT_BASE_URL = "https://api.github.com"
PAGE_SIZE = 100
MAX_PAGES = 10
# Emails are only on the per-user profile, so resolving them costs one call each.
MAX_PROFILE_LOOKUPS = 200
MAX_TEXT = 4000

_REPO = FieldSpec(
    name="repo",
    label="Repository",
    required=True,
    placeholder="owner/name",
    help="The owner can be left out when the connection has an organization.",
)
_STATE = FieldSpec(
    name="state", label="State", type="select", options=["open", "closed", "all"], default="open"
)


class GitHubConnector(Connector):
    spec = ConnectorSpec(
        key="github",
        title="GitHub",
        description="Work with issues and pull requests, and map repositories and members.",
        config_fields=[
            FieldSpec(
                name="token",
                label="Access token",
                required=True,
                secret=True,
                placeholder="ghp_... or github_pat_...",
                help="Personal access token with repo and read:org access.",
            ),
            FieldSpec(
                name="org",
                label="Organization",
                placeholder="acme",
                help="Used by the sync operations and as the default repository owner.",
            ),
            FieldSpec(
                name="base_url",
                label="API URL",
                default=DEFAULT_BASE_URL,
                help="Change only for GitHub Enterprise Server (https://host/api/v3).",
            ),
        ],
        operations=[
            OperationSpec(
                name="create_issue",
                title="Create issue",
                params=[
                    _REPO,
                    FieldSpec(name="title", label="Title", required=True),
                    FieldSpec(name="body", label="Body", type="text"),
                    FieldSpec(name="labels", label="Labels", help="Comma-separated."),
                ],
            ),
            OperationSpec(
                name="comment_on_issue",
                title="Comment on issue",
                description="Add a comment to an issue or pull request.",
                params=[
                    _REPO,
                    FieldSpec(name="number", label="Issue number", type="number", required=True),
                    FieldSpec(name="body", label="Comment", type="text", required=True),
                ],
            ),
            OperationSpec(name="list_issues", title="List issues", params=[_REPO, _STATE]),
            OperationSpec(
                name="list_pull_requests", title="List pull requests", params=[_REPO, _STATE]
            ),
            OperationSpec(name="get_repo", title="Get repository", params=[_REPO]),
            OperationSpec(
                name="sync_repos",
                title="Sync repositories",
                kind="sync",
                description="Add each repository of the organization (or of the token's user) "
                "as a Project.",
                params=[FieldSpec(name="org", label="Organization", help="Overrides the "
                                  "connection's organization.")],
            ),
            OperationSpec(
                name="sync_members",
                title="Sync members",
                kind="sync",
                description="Add the organization as a Team and its members as People.",
                params=[
                    FieldSpec(name="org", label="Organization", help="Overrides the "
                              "connection's organization."),
                    FieldSpec(
                        name="resolve_emails",
                        label="Look up emails",
                        type="boolean",
                        default=True,
                        help="Fetch each profile so people merge with other systems by email.",
                    ),
                ],
            ),
            OperationSpec(
                name="sync_issues",
                title="Sync issues",
                kind="sync",
                description="Add a repository's issues and pull requests as Tickets, linked to "
                "their authors and assignees.",
                params=[
                    _REPO,
                    FieldSpec(
                        name="state",
                        label="State",
                        type="select",
                        options=["open", "closed", "all"],
                        default="all",
                    ),
                    FieldSpec(name="limit", label="Limit", type="number", default=200),
                    FieldSpec(
                        name="resolve_emails", label="Look up emails", type="boolean", default=True
                    ),
                ],
            ),
        ],
    )

    # --- transport -----------------------------------------------------------
    @staticmethod
    def _base(ctx: ConnectorContext) -> str:
        return str(ctx.config.get("base_url") or DEFAULT_BASE_URL).rstrip("/")

    def _request(self, ctx: ConnectorContext, method: str, url: str, **kwargs: Any) -> Any:
        token = require(ctx.secrets, "token", "github")
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if not url.startswith("http"):
            url = self._base(ctx) + url
        return send(ctx, "github", method, url, headers=headers, **kwargs)

    def _get(self, ctx: ConnectorContext, path: str, **params: Any) -> Any:
        return json_body(self._request(ctx, "GET", path, params=params or None), "github")

    def _post(self, ctx: ConnectorContext, path: str, payload: dict[str, Any]) -> Any:
        return json_body(self._request(ctx, "POST", path, json=payload), "github")

    def _paginate(
        self, ctx: ConnectorContext, path: str, cap: int | None = None, **params: Any
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        resp = self._request(ctx, "GET", path, params={"per_page": PAGE_SIZE, **params})
        for page in range(MAX_PAGES):
            items.extend(json_body(resp, "github"))
            next_url = resp.links.get("next", {}).get("url")
            if not next_url or page == MAX_PAGES - 1 or (cap is not None and len(items) >= cap):
                break
            resp = self._request(ctx, "GET", next_url)  # the link already carries the query
        return items if cap is None else items[:cap]

    # --- params --------------------------------------------------------------
    @staticmethod
    def _repo(params: dict[str, Any], ctx: ConnectorContext) -> str:
        repo = str(params["repo"]).strip().strip("/")
        if "/" not in repo and ctx.config.get("org"):
            repo = f"{ctx.config['org']}/{repo}"
        if repo.count("/") != 1 or not all(repo.split("/")):
            raise ConnectorError(f"github: repo must look like owner/name, got {params['repo']!r}")
        return repo

    @staticmethod
    def _org(params: dict[str, Any], ctx: ConnectorContext) -> str | None:
        org = params.get("org") or ctx.config.get("org")
        return str(org).strip() if org else None

    # --- shaping -------------------------------------------------------------
    @staticmethod
    def _issue(issue: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "state": issue.get("state"),
            "url": issue.get("html_url"),
            "author": (issue.get("user") or {}).get("login"),
            "assignees": [a.get("login") for a in issue.get("assignees") or []],
            "labels": [
                label.get("name") if isinstance(label, dict) else label
                for label in issue.get("labels") or []
            ],
            "created_at": issue.get("created_at"),
            "updated_at": issue.get("updated_at"),
        }

    @staticmethod
    def _repo_summary(repo: dict[str, Any]) -> dict[str, Any]:
        return {
            "full_name": repo.get("full_name"),
            "description": repo.get("description"),
            "url": repo.get("html_url"),
            "private": bool(repo.get("private")),
            "archived": bool(repo.get("archived")),
            "default_branch": repo.get("default_branch"),
            "language": repo.get("language"),
            "stars": repo.get("stargazers_count"),
            "open_issues": repo.get("open_issues_count"),
            "pushed_at": repo.get("pushed_at"),
        }

    def _project_node(self, repo: dict[str, Any]) -> NodeUpsert:
        info = self._repo_summary(repo)
        full_name = info.pop("full_name")
        return NodeUpsert(
            label="Project",
            key=entity_key("github", "repo", full_name),
            props={"name": full_name, "kind": "github_repo", **info},
        )

    def _person_node(
        self,
        ctx: ConnectorContext,
        user: dict[str, Any],
        cache: dict[str, NodeUpsert],
        resolve_emails: bool,
    ) -> NodeUpsert:
        """Person for a GitHub user. List endpoints only give the login, so the
        profile is fetched (up to MAX_PROFILE_LOOKUPS per run) to find an email."""
        login = user["login"]
        if login in cache:
            return cache[login]
        profile = user
        if resolve_emails and len(cache) < MAX_PROFILE_LOOKUPS:
            profile = self._get(ctx, f"/users/{login}")
        node = NodeUpsert(
            label="Person",
            key=person_key(profile.get("email"), "github", login),
            props={
                "name": profile.get("name") or login,
                "email": profile.get("email"),
                "github_login": login,
                "company": profile.get("company"),
                "url": profile.get("html_url") or user.get("html_url"),
            },
        )
        cache[login] = node
        return node

    # --- operations ----------------------------------------------------------
    def execute(
        self, operation: str, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        self.validate_params(operation, params)
        return getattr(self, f"_op_{operation}")(params, ctx)

    def test(self, ctx: ConnectorContext) -> dict[str, Any]:
        user = self._get(ctx, "/user")
        return {"login": user.get("login"), "name": user.get("name"), "id": user.get("id")}

    def _op_create_issue(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        repo = self._repo(params, ctx)
        payload: dict[str, Any] = {"title": params["title"]}
        if params.get("body"):
            payload["body"] = params["body"]
        labels = as_list(params.get("labels"))
        if labels:
            payload["labels"] = labels
        issue = self._post(ctx, f"/repos/{repo}/issues", payload)
        return OperationResult(output={"repo": repo, **self._issue(issue)})

    def _op_comment_on_issue(
        self, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        repo = self._repo(params, ctx)
        number = as_int(params["number"], 0, 1, 10**9)
        comment = self._post(
            ctx, f"/repos/{repo}/issues/{number}/comments", {"body": params["body"]}
        )
        return OperationResult(
            output={"repo": repo, "number": number, "id": comment.get("id"),
                    "url": comment.get("html_url")}
        )

    def _op_list_issues(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        repo = self._repo(params, ctx)
        found = self._paginate(ctx, f"/repos/{repo}/issues", state=params.get("state") or "open")
        # The issues endpoint also returns pull requests.
        issues = [self._issue(i) for i in found if "pull_request" not in i]
        return OperationResult(output={"repo": repo, "issues": issues, "count": len(issues)})

    def _op_list_pull_requests(
        self, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        repo = self._repo(params, ctx)
        found = self._paginate(ctx, f"/repos/{repo}/pulls", state=params.get("state") or "open")
        pulls = [
            {
                **self._issue(p),
                "draft": bool(p.get("draft")),
                "head": (p.get("head") or {}).get("ref"),
                "base": (p.get("base") or {}).get("ref"),
            }
            for p in found
        ]
        return OperationResult(
            output={"repo": repo, "pull_requests": pulls, "count": len(pulls)}
        )

    def _op_get_repo(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        repo = self._repo(params, ctx)
        return OperationResult(output=self._repo_summary(self._get(ctx, f"/repos/{repo}")))

    def _op_sync_repos(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        org = self._org(params, ctx)
        if org:
            repos = self._paginate(ctx, f"/orgs/{org}/repos", type="all")
        else:
            repos = self._paginate(ctx, "/user/repos", affiliation="owner")
        delta = GraphDelta(nodes=[self._project_node(r) for r in repos])
        if org:
            team_key = entity_key("github", "org", org)
            delta.nodes.append(self._org_node(org, ctx))
            delta.edges = [
                EdgeUpsert(
                    src_label="Team",
                    src_key=team_key,
                    type="OWNS",
                    dst_label="Project",
                    dst_key=node.key,
                )
                for node in delta.nodes
                if node.label == "Project"
            ]
        return OperationResult(output={"projects": len(repos), "org": org}, graph=delta)

    def _org_node(self, org: str, ctx: ConnectorContext) -> NodeUpsert:
        on_github_com = self._base(ctx) == DEFAULT_BASE_URL
        return NodeUpsert(
            label="Team",
            key=entity_key("github", "org", org),
            props={
                "name": org,
                "kind": "github_org",
                "url": f"https://github.com/{org}" if on_github_com else None,
            },
        )

    def _op_sync_members(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        org = self._org(params, ctx)
        if not org:
            raise ConnectorError("github: sync_members needs an organization")
        resolve = as_bool(params.get("resolve_emails"), True)
        team = self._org_node(org, ctx)
        cache: dict[str, NodeUpsert] = {}
        delta = GraphDelta(nodes=[team])
        for member in self._paginate(ctx, f"/orgs/{org}/members"):
            person = self._person_node(ctx, member, cache, resolve)
            delta.edges.append(
                EdgeUpsert(
                    src_label="Person",
                    src_key=person.key,
                    type="MEMBER_OF",
                    dst_label="Team",
                    dst_key=team.key,
                )
            )
        delta.nodes.extend(cache.values())
        return OperationResult(output={"org": org, "people": len(cache)}, graph=delta)

    def _op_sync_issues(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        repo = self._repo(params, ctx)
        resolve = as_bool(params.get("resolve_emails"), True)
        limit = as_int(params.get("limit"), 200, 1, PAGE_SIZE * MAX_PAGES)
        issues = self._paginate(
            ctx, f"/repos/{repo}/issues", cap=limit, state=params.get("state") or "all"
        )

        project_key = entity_key("github", "repo", repo)
        delta = GraphDelta(
            nodes=[
                NodeUpsert(
                    label="Project", key=project_key, props={"name": repo, "kind": "github_repo"}
                )
            ]
        )
        people: dict[str, NodeUpsert] = {}
        for issue in issues:
            info = self._issue(issue)
            ticket_key = entity_key("github", "issue", f"{repo}#{info['number']}")
            delta.nodes.append(
                NodeUpsert(
                    label="Ticket",
                    key=ticket_key,
                    props={
                        "name": f"{repo}#{info['number']}: {info['title']}",
                        "title": info["title"],
                        "number": info["number"],
                        "state": info["state"],
                        "kind": "pull_request" if "pull_request" in issue else "issue",
                        "labels": info["labels"],
                        "url": info["url"],
                        "created_at": info["created_at"],
                        "closed_at": issue.get("closed_at"),
                        TEXT_PROP: (issue.get("body") or "")[:MAX_TEXT],
                    },
                )
            )
            delta.edges.append(
                EdgeUpsert(
                    src_label="Ticket",
                    src_key=ticket_key,
                    type="PART_OF",
                    dst_label="Project",
                    dst_key=project_key,
                )
            )
            author_info = issue.get("user") or {}
            if author_info.get("login") and author_info.get("type") != "Bot":
                author = self._person_node(ctx, issue["user"], people, resolve)
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Person",
                        src_key=author.key,
                        type="AUTHORED",
                        dst_label="Ticket",
                        dst_key=ticket_key,
                    )
                )
            for assignee in issue.get("assignees") or []:
                person = self._person_node(ctx, assignee, people, resolve)
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Ticket",
                        src_key=ticket_key,
                        type="ASSIGNED_TO",
                        dst_label="Person",
                        dst_key=person.key,
                    )
                )
        delta.nodes.extend(people.values())
        return OperationResult(
            output={"repo": repo, "tickets": len(issues), "people": len(people)}, graph=delta
        )


register(GitHubConnector())
