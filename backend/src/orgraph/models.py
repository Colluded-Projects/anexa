"""Stored domain models. Each is one node in the system graph (see repos.py).

Vocabulary:
  Connection  credentials + config for one connector (Slack, GitHub, Jira, Google, Agent)
  Action      one reusable connector call: connection + operation + params
  Operator    a schedulable workflow; each task runs one Action
  Schedule    cron trigger for an Operator
  Run         one execution of an Action or an Operator
  Agent       placeholder for a future AI agent, linked to actions/operators
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> str:
    """UTC timestamp as an ISO-8601 string; sorts lexicographically."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Stored(BaseModel):
    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class User(Stored):
    email: str
    name: str = ""
    password_hash: str


class Workspace(Stored):
    name: str
    slug: str


Role = Literal["owner", "member"]


class ApiKey(Stored):
    workspace_id: str
    user_id: str
    name: str
    prefix: str  # first characters of the key, shown in the UI
    key_hash: str  # sha256 hex of the full key
    last_used_at: str | None = None


class WorkspaceScoped(Stored):
    workspace_id: str


ConnectionStatus = Literal["untested", "ok", "error"]


class Connection(WorkspaceScoped):
    name: str
    connector: str  # key in the connector registry: slack, github, jira, google, agent
    config: dict[str, Any] = Field(default_factory=dict)  # non-secret settings
    secrets_enc: str = ""  # Fernet-encrypted JSON object of secret fields
    secret_fields: list[str] = Field(default_factory=list)  # names of the secrets that are set
    status: ConnectionStatus = "untested"
    status_detail: str = ""


class Action(WorkspaceScoped):
    name: str
    description: str = ""
    connection_id: str
    operation: str  # operation name on the connection's connector
    params: dict[str, Any] = Field(default_factory=dict)  # may contain {{ templates }}


class OperatorTask(BaseModel):
    key: str  # unique within the operator; referenced as {{ tasks.<key>.output... }}
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)  # merged over the action's params
    continue_on_error: bool = False


class Operator(WorkspaceScoped):
    name: str
    description: str = ""
    tasks: list[OperatorTask] = Field(default_factory=list)
    enabled: bool = True


class Schedule(WorkspaceScoped):
    operator_id: str
    cron: str  # 5-field crontab expression
    timezone: str = "UTC"
    enabled: bool = True
    input: dict[str, Any] = Field(default_factory=dict)
    next_run_at: str | None = None
    last_run_at: str | None = None


RunStatus = Literal["queued", "running", "succeeded", "failed"]
RunKind = Literal["action", "operator"]
RunTrigger = Literal["manual", "schedule", "mcp", "api"]


class TaskResult(BaseModel):
    key: str
    action_id: str
    action_name: str = ""
    status: Literal["pending", "running", "succeeded", "failed", "skipped"] = "pending"
    output: dict[str, Any] | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class Run(WorkspaceScoped):
    kind: RunKind
    target_id: str
    target_name: str = ""
    status: RunStatus = "queued"
    trigger: RunTrigger = "manual"
    triggered_by: str | None = None  # user id, schedule id or api key id
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error: str | None = None
    tasks: list[TaskResult] = Field(default_factory=list)  # one entry for an action run
    started_at: str | None = None
    finished_at: str | None = None


AgentProvider = Literal["claude_code", "openrouter", "jev", "custom"]


class Agent(WorkspaceScoped):
    name: str
    description: str = ""
    provider: AgentProvider = "claude_code"
    model: str = ""
    instructions: str = ""
    action_ids: list[str] = Field(default_factory=list)
    operator_ids: list[str] = Field(default_factory=list)
    # No agent runtime exists yet; this never changes from "not_connected".
    status: Literal["not_connected"] = "not_connected"
