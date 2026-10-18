from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...models import Agent
from ..common import invalid, scoped
from ..deps import WorkspaceCtx, WorkspaceDep
from ..schemas import AgentIn, AgentOut, AgentPatch

router = APIRouter(prefix="/api/workspaces/{ws}/agents", tags=["agents"])


def _out(agent: Agent) -> AgentOut:
    return AgentOut(**agent.model_dump(exclude={"workspace_id"}))


def _check_links(ctx: WorkspaceCtx, action_ids: list[str], operator_ids: list[str]) -> None:
    for repo, ids, what in (
        (ctx.repos.actions, action_ids, "action"),
        (ctx.repos.operators, operator_ids, "operator"),
    ):
        for id in ids:
            obj = repo.get(id)
            if obj is None or obj.workspace_id != ctx.id:
                raise invalid(f"{what} {id!r} does not exist in this workspace")


@router.get("")
def list_agents(ctx: WorkspaceDep) -> list[AgentOut]:
    return [_out(a) for a in ctx.repos.agents.list(workspace_id=ctx.id)]


@router.post("", status_code=201)
def create(body: AgentIn, ctx: WorkspaceDep) -> AgentOut:
    _check_links(ctx, body.action_ids, body.operator_ids)
    agent = Agent(workspace_id=ctx.id, **{**body.model_dump(), "name": body.name.strip()})
    return _out(ctx.repos.agents.create(agent))


@router.get("/{agent_id}")
def get(agent_id: str, ctx: WorkspaceDep) -> AgentOut:
    return _out(scoped(ctx.repos.agents, agent_id, ctx, "agent"))


@router.patch("/{agent_id}")
def update(agent_id: str, body: AgentPatch, ctx: WorkspaceDep) -> AgentOut:
    agent = scoped(ctx.repos.agents, agent_id, ctx, "agent")
    changes: dict[str, Any] = {
        k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None
    }
    _check_links(ctx, changes.get("action_ids", []), changes.get("operator_ids", []))
    return _out(ctx.repos.agents.update(agent.id, **changes) if changes else agent)


@router.delete("/{agent_id}", status_code=204)
def delete(agent_id: str, ctx: WorkspaceDep) -> None:
    agent = scoped(ctx.repos.agents, agent_id, ctx, "agent")
    ctx.repos.agents.delete(agent.id)
