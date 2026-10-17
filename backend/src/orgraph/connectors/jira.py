from __future__ import annotations

from typing import Any

from ..graph.ontology import TEXT_PROP, entity_key, person_key
from . import register
from ._http import as_int, json_body, require, send
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

PAGE_SIZE = 50
MAX_PAGES = 20
ISSUE_FIELDS = [
    "summary",
    "status",
    "issuetype",
    "priority",
    "assignee",
    "reporter",
    "project",
    "created",
    "updated",
    "description",
]
MAX_TEXT = 4000


def to_adf(text: Any) -> dict[str, Any]:
    """Plain text as an Atlassian Document Format doc, one paragraph per line.
    A value that already is an ADF doc is passed through."""
    if isinstance(text, dict) and text.get("type") == "doc":
        return text
    paragraphs = []
    for line in str(text).splitlines() or [""]:
        content = [{"type": "text", "text": line}] if line else []
        paragraphs.append({"type": "paragraph", "content": content})
    return {"type": "doc", "version": 1, "content": paragraphs}


def adf_text(value: Any) -> str:
    """Plain text of an Atlassian Document Format value (or a plain string)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(t for t in (adf_text(v) for v in value) if t)
    if isinstance(value, dict):
        return " ".join(t for t in (value.get("text") or "", adf_text(value.get("content"))) if t)
    return ""


class JiraConnector(Connector):
    spec = ConnectorSpec(
        key="jira",
        title="Jira",
        description="Create and move issues in Jira Cloud, and map projects and tickets.",
        config_fields=[
            FieldSpec(
                name="base_url",
                label="Site URL",
                required=True,
                placeholder="https://your-company.atlassian.net",
            ),
            FieldSpec(
                name="email",
                label="Account email",
                required=True,
                help="The Atlassian account the API token belongs to.",
            ),
            FieldSpec(
                name="api_token",
                label="API token",
                required=True,
                secret=True,
                help="Create one at id.atlassian.com under Security, API tokens.",
            ),
        ],
        operations=[
            OperationSpec(
                name="create_issue",
                title="Create issue",
                params=[
                    FieldSpec(name="project", label="Project key", required=True,
                              placeholder="ENG"),
                    FieldSpec(name="summary", label="Summary", required=True),
                    FieldSpec(name="description", label="Description", type="text"),
                    FieldSpec(name="issue_type", label="Issue type", default="Task"),
                ],
            ),
            OperationSpec(
                name="add_comment",
                title="Add comment",
                params=[
                    FieldSpec(name="issue", label="Issue key", required=True,
                              placeholder="ENG-123"),
                    FieldSpec(name="body", label="Comment", type="text", required=True),
                ],
            ),
            OperationSpec(
                name="search_issues",
                title="Search issues",
                description="Find issues with a JQL query.",
                params=[
                    FieldSpec(
                        name="jql",
                        label="JQL",
                        type="text",
                        required=True,
                        placeholder="project = ENG AND status != Done ORDER BY updated DESC",
                    ),
                    FieldSpec(name="limit", label="Limit", type="number", default=50),
                ],
            ),
            OperationSpec(
                name="transition_issue",
                title="Transition issue",
                description="Move an issue through its workflow.",
                params=[
                    FieldSpec(name="issue", label="Issue key", required=True,
                              placeholder="ENG-123"),
                    FieldSpec(
                        name="transition",
                        label="Transition",
                        required=True,
                        placeholder="Done",
                        help="Transition name, target status name, or transition id.",
                    ),
                ],
            ),
            OperationSpec(
                name="sync_projects",
                title="Sync projects",
                kind="sync",
                description="Add each Jira project as a Project, owned by its lead.",
            ),
            OperationSpec(
                name="sync_issues",
                title="Sync issues",
                kind="sync",
                description="Add issues as Tickets linked to their project, assignee and "
                "reporter. Give a project key or a JQL query.",
                params=[
                    FieldSpec(name="project", label="Project key", placeholder="ENG"),
                    FieldSpec(name="jql", label="JQL", type="text",
                              help="Takes precedence over the project key."),
                    FieldSpec(name="limit", label="Limit", type="number", default=200),
                ],
            ),
        ],
    )

    # --- transport -----------------------------------------------------------
    @staticmethod
    def _base(ctx: ConnectorContext) -> str:
        return require(ctx.config, "base_url", "jira").rstrip("/")

    def _request(self, ctx: ConnectorContext, method: str, path: str, **kwargs: Any) -> Any:
        auth = (require(ctx.config, "email", "jira"), require(ctx.secrets, "api_token", "jira"))
        resp = send(
            ctx,
            "jira",
            method,
            f"{self._base(ctx)}/rest/api/3{path}",
            auth=auth,
            headers={"Accept": "application/json"},
            **kwargs,
        )
        return json_body(resp, "jira")

    def _search(self, ctx: ConnectorContext, jql: str, limit: int) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(MAX_PAGES):
            payload: dict[str, Any] = {
                "jql": jql,
                "maxResults": min(PAGE_SIZE * 2, limit - len(issues)),
                "fields": ISSUE_FIELDS,
            }
            if token:
                payload["nextPageToken"] = token
            body = self._request(ctx, "POST", "/search/jql", json=payload)
            issues.extend(body.get("issues") or [])
            token = body.get("nextPageToken")
            if not token or body.get("isLast") or len(issues) >= limit:
                break
        return issues[:limit]

    # --- shaping -------------------------------------------------------------
    def _issue(self, ctx: ConnectorContext, issue: dict[str, Any]) -> dict[str, Any]:
        fields = issue.get("fields") or {}

        def name_of(field: str, attr: str = "name") -> Any:
            return (fields.get(field) or {}).get(attr)

        return {
            "key": issue.get("key"),
            "summary": fields.get("summary"),
            "status": name_of("status"),
            "type": name_of("issuetype"),
            "priority": name_of("priority"),
            "assignee": name_of("assignee", "displayName"),
            "reporter": name_of("reporter", "displayName"),
            "project": name_of("project", "key"),
            "created_at": fields.get("created"),
            "updated_at": fields.get("updated"),
            "url": f"{self._base(ctx)}/browse/{issue.get('key')}",
        }

    @staticmethod
    def _person_node(user: dict[str, Any]) -> NodeUpsert:
        # emailAddress is only present when the user's privacy settings allow it.
        email = user.get("emailAddress")
        return NodeUpsert(
            label="Person",
            key=person_key(email, "jira", user.get("accountId", "")),
            props={
                "name": user.get("displayName") or email or user.get("accountId"),
                "email": email,
                "jira_account_id": user.get("accountId"),
            },
        )

    def _project_node(self, ctx: ConnectorContext, project: dict[str, Any]) -> NodeUpsert:
        key = project.get("key")
        return NodeUpsert(
            label="Project",
            key=entity_key("jira", "project", key),
            props={
                "name": project.get("name") or key,
                "kind": "jira_project",
                "jira_key": key,
                "project_type": project.get("projectTypeKey"),
                "url": f"{self._base(ctx)}/browse/{key}",
            },
        )

    # --- operations ----------------------------------------------------------
    def execute(
        self, operation: str, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        self.validate_params(operation, params)
        return getattr(self, f"_op_{operation}")(params, ctx)

    def test(self, ctx: ConnectorContext) -> dict[str, Any]:
        me = self._request(ctx, "GET", "/myself")
        return {
            "account_id": me.get("accountId"),
            "name": me.get("displayName"),
            "email": me.get("emailAddress"),
        }

    def _op_create_issue(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        fields: dict[str, Any] = {
            "project": {"key": params["project"]},
            "summary": params["summary"],
            "issuetype": {"name": params.get("issue_type") or "Task"},
        }
        if params.get("description"):
            fields["description"] = to_adf(params["description"])
        created = self._request(ctx, "POST", "/issue", json={"fields": fields})
        key = created.get("key")
        return OperationResult(
            output={"key": key, "id": created.get("id"), "url": f"{self._base(ctx)}/browse/{key}"}
        )

    def _op_add_comment(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        issue = params["issue"]
        comment = self._request(
            ctx, "POST", f"/issue/{issue}/comment", json={"body": to_adf(params["body"])}
        )
        return OperationResult(
            output={"issue": issue, "id": comment.get("id"),
                    "url": f"{self._base(ctx)}/browse/{issue}"}
        )

    def _op_search_issues(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        limit = as_int(params.get("limit"), 50, 1, PAGE_SIZE * MAX_PAGES)
        issues = [self._issue(ctx, i) for i in self._search(ctx, params["jql"], limit)]
        return OperationResult(output={"issues": issues, "count": len(issues)})

    def _op_transition_issue(
        self, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        issue = params["issue"]
        wanted = str(params["transition"]).strip().lower()
        available = self._request(ctx, "GET", f"/issue/{issue}/transitions").get("transitions", [])
        match = next(
            (
                t
                for t in available
                if wanted
                in (
                    str(t.get("id", "")).lower(),
                    str(t.get("name", "")).lower(),
                    str((t.get("to") or {}).get("name", "")).lower(),
                )
            ),
            None,
        )
        if match is None:
            names = ", ".join(t.get("name", "?") for t in available) or "none"
            raise ConnectorError(
                f"jira: {issue} has no transition {params['transition']!r} (available: {names})"
            )
        self._request(
            ctx, "POST", f"/issue/{issue}/transitions", json={"transition": {"id": match["id"]}}
        )
        return OperationResult(
            output={
                "issue": issue,
                "transition": match.get("name"),
                "status": (match.get("to") or {}).get("name"),
                "url": f"{self._base(ctx)}/browse/{issue}",
            }
        )

    def _op_sync_projects(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        projects: list[dict[str, Any]] = []
        for _ in range(MAX_PAGES):
            body = self._request(
                ctx,
                "GET",
                "/project/search",
                params={"startAt": len(projects), "maxResults": PAGE_SIZE, "expand": "lead"},
            )
            values = body.get("values") or []
            projects.extend(values)
            if body.get("isLast", True) or not values:
                break

        delta = GraphDelta()
        people: dict[str, NodeUpsert] = {}
        for project in projects:
            node = self._project_node(ctx, project)
            delta.nodes.append(node)
            lead = project.get("lead") or {}
            if lead.get("accountId"):
                person = people.setdefault(lead["accountId"], self._person_node(lead))
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Person",
                        src_key=person.key,
                        type="OWNS",
                        dst_label="Project",
                        dst_key=node.key,
                    )
                )
        delta.nodes.extend(people.values())
        return OperationResult(
            output={"projects": len(projects), "people": len(people)}, graph=delta
        )

    def _op_sync_issues(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        jql = params.get("jql")
        if not jql:
            if not params.get("project"):
                raise ConnectorError("jira: sync_issues needs a project key or a JQL query")
            project = str(params["project"]).replace('"', '\\"')
            jql = f'project = "{project}" ORDER BY updated DESC'
        limit = as_int(params.get("limit"), 200, 1, PAGE_SIZE * MAX_PAGES)
        issues = self._search(ctx, jql, limit)

        delta = GraphDelta()
        projects: dict[str, NodeUpsert] = {}
        people: dict[str, NodeUpsert] = {}
        for issue in issues:
            info = self._issue(ctx, issue)
            fields = issue.get("fields") or {}
            ticket_key = entity_key("jira", "issue", info["key"])
            delta.nodes.append(
                NodeUpsert(
                    label="Ticket",
                    key=ticket_key,
                    props={
                        "name": f"{info['key']}: {info['summary']}",
                        "title": info["summary"],
                        "jira_key": info["key"],
                        "state": info["status"],
                        "kind": info["type"],
                        "priority": info["priority"],
                        "url": info["url"],
                        "created_at": info["created_at"],
                        TEXT_PROP: adf_text(fields.get("description"))[:MAX_TEXT],
                    },
                )
            )
            project = fields.get("project") or {}
            if project.get("key"):
                node = projects.setdefault(project["key"], self._project_node(ctx, project))
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Ticket",
                        src_key=ticket_key,
                        type="PART_OF",
                        dst_label="Project",
                        dst_key=node.key,
                    )
                )
            assignee = fields.get("assignee") or {}
            if assignee.get("accountId"):
                person = people.setdefault(assignee["accountId"], self._person_node(assignee))
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Ticket",
                        src_key=ticket_key,
                        type="ASSIGNED_TO",
                        dst_label="Person",
                        dst_key=person.key,
                    )
                )
            reporter = fields.get("reporter") or {}
            if reporter.get("accountId"):
                person = people.setdefault(reporter["accountId"], self._person_node(reporter))
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Person",
                        src_key=person.key,
                        type="AUTHORED",
                        dst_label="Ticket",
                        dst_key=ticket_key,
                    )
                )
        delta.nodes.extend([*projects.values(), *people.values()])
        return OperationResult(
            output={"tickets": len(issues), "projects": len(projects), "people": len(people),
                    "jql": jql},
            graph=delta,
        )


register(JiraConnector())
