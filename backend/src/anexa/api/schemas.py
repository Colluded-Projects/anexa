"""Request and response bodies, mirroring docs/api.md."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, EmailStr, Field

from ..models import (
    AgentProvider,
    ConnectionStatus,
    Role,
    RunKind,
    RunStatus,
    RunTrigger,
    TaskResult,
)

NameStr = Annotated[str, Field(min_length=1, max_length=200)]


# --- auth ------------------------------------------------------------------
class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    name: str = Field(default="", max_length=200)
    workspace_name: str | None = Field(default=None, max_length=200)


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: str


class WorkspaceOut(BaseModel):
    id: str
    name: str
    slug: str
    role: Role
    created_at: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SignupOut(LoginOut):
    workspace: WorkspaceOut


class MeOut(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]


# --- workspaces --------------------------------------------------------------
class WorkspaceIn(BaseModel):
    name: NameStr


class MemberIn(BaseModel):
    email: str
    role: Role = "member"


class MemberOut(BaseModel):
    user_id: str
    email: str
    name: str
    role: Role


class ApiKeyIn(BaseModel):
    name: NameStr


class ApiKeyOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: str
    last_used_at: str | None = None


class ApiKeyCreated(ApiKeyOut):
    key: str


# --- connections -------------------------------------------------------------
class ConnectionIn(BaseModel):
    name: NameStr
    connector: str
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, Any] = Field(default_factory=dict)


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    secrets: dict[str, Any] | None = None


class ConnectionOut(BaseModel):
    id: str
    name: str
    connector: str
    config: dict[str, Any]
    secret_fields: list[str]
    status: ConnectionStatus
    status_detail: str
    created_at: str
    updated_at: str


class ConnectionTestOut(BaseModel):
    ok: bool
    detail: str
    identity: dict[str, Any]


# --- actions -----------------------------------------------------------------
class ActionIn(BaseModel):
    name: NameStr
    description: str = ""
    connection_id: str
    operation: str
    params: dict[str, Any] = Field(default_factory=dict)


class ActionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    connection_id: str | None = None
    operation: str | None = None
    params: dict[str, Any] | None = None


class ActionOut(BaseModel):
    id: str
    name: str
    description: str
    connection_id: str
    connection_name: str
    connector: str
    operation: str
    params: dict[str, Any]
    created_at: str
    updated_at: str


class RunIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


# --- operators ---------------------------------------------------------------
class TaskIn(BaseModel):
    key: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    continue_on_error: bool = False


class OperatorIn(BaseModel):
    name: NameStr
    description: str = ""
    tasks: list[TaskIn] = Field(default_factory=list)
    enabled: bool = True


class OperatorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    tasks: list[TaskIn] | None = None
    enabled: bool | None = None


class OperatorOut(BaseModel):
    id: str
    name: str
    description: str
    enabled: bool
    tasks: list[TaskIn]
    created_at: str
    updated_at: str


# --- schedules ---------------------------------------------------------------
class ScheduleIn(BaseModel):
    operator_id: str
    cron: str
    timezone: str = "UTC"
    enabled: bool = True
    input: dict[str, Any] = Field(default_factory=dict)


class SchedulePatch(BaseModel):
    cron: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    input: dict[str, Any] | None = None


class ScheduleOut(BaseModel):
    id: str
    operator_id: str
    operator_name: str
    cron: str
    timezone: str
    enabled: bool
    input: dict[str, Any]
    next_run_at: str | None
    last_run_at: str | None
    created_at: str
    updated_at: str


# --- runs --------------------------------------------------------------------
class RunOut(BaseModel):
    id: str
    kind: RunKind
    target_id: str
    target_name: str
    status: RunStatus
    trigger: RunTrigger
    triggered_by: str | None
    input: dict[str, Any]
    output: dict[str, Any] | None
    error: str | None
    tasks: list[TaskResult]
    created_at: str
    started_at: str | None
    finished_at: str | None


class SummaryOut(BaseModel):
    counts: dict[str, int]
    runs_by_status: dict[str, int]
    recent_runs: list[RunOut]
    graph: dict[str, int]


# --- agents ------------------------------------------------------------------
class AgentIn(BaseModel):
    name: NameStr
    description: str = ""
    provider: AgentProvider = "claude_code"
    model: str = ""
    instructions: str = ""
    action_ids: list[str] = Field(default_factory=list)
    operator_ids: list[str] = Field(default_factory=list)


class AgentPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    provider: AgentProvider | None = None
    model: str | None = None
    instructions: str | None = None
    action_ids: list[str] | None = None
    operator_ids: list[str] | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    description: str
    provider: AgentProvider
    model: str
    instructions: str
    action_ids: list[str]
    operator_ids: list[str]
    status: str
    created_at: str
    updated_at: str


# --- company graph -----------------------------------------------------------
class GraphNodeIn(BaseModel):
    label: str
    name: str = Field(min_length=1, max_length=500)
    key: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class GraphNodePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    props: dict[str, Any] | None = None


class GraphNodeOut(BaseModel):
    id: str
    label: str
    name: str
    key: str
    source: str
    url: str | None
    props: dict[str, Any]
    updated_at: str | None


class GraphEdgeIn(BaseModel):
    src: str
    type: str
    dst: str
    props: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeOut(BaseModel):
    src: str
    type: str
    dst: str
    props: dict[str, Any]


class LinkEdgeIn(BaseModel):
    src: str
    type: str
    dst: str


class SamePersonProposal(BaseModel):
    a: str
    b: str
    reason: str
    confidence: float


class RelatedProposal(BaseModel):
    a: str
    b: str
    quote: str
    confidence: float


class DecisionProposal(BaseModel):
    source: str
    summary: str
    quote: str
    decided_by: list[str] = Field(default_factory=list)
    affects: list[str] = Field(default_factory=list)
    confidence: float


class LinkProposalsIn(BaseModel):
    """Links proposed by an outside model (e.g. Claude Code over MCP)."""

    same_person: list[SamePersonProposal] = Field(default_factory=list)
    related: list[RelatedProposal] = Field(default_factory=list)
    decisions: list[DecisionProposal] = Field(default_factory=list)


class LinkReviewOut(BaseModel):
    src: str
    src_name: str
    type: str
    dst: str
    dst_name: str
    method: str
    confidence: float
    evidence: str | None


class GraphNodeDetail(GraphNodeOut):
    edges: list[GraphEdgeOut]
    neighbors: list[GraphNodeOut]


class SubgraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]


class GraphStatsOut(BaseModel):
    nodes: dict[str, int]
    total_nodes: int
    total_edges: int


class GraphQueryIn(BaseModel):
    cypher: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class GraphQueryOut(BaseModel):
    rows: list[dict[str, Any]]
