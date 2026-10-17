from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...models import ApiKey
from ...repos import Repos
from ...security import generate_api_key
from ..common import run_out, workspace_out
from ..deps import OwnerDep, Principal, PrincipalDep, ReposDep, WorkspaceDep
from ..schemas import (
    ApiKeyCreated,
    ApiKeyIn,
    ApiKeyOut,
    MemberIn,
    MemberOut,
    SummaryOut,
    WorkspaceIn,
    WorkspaceOut,
)
from .auth import create_workspace

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def visible_workspaces(principal: Principal, repos: Repos) -> list[WorkspaceOut]:
    """The caller's workspaces; an API key only ever sees its own."""
    pairs = repos.workspaces_for(principal.user.id)
    if principal.api_key is not None:
        pairs = [(ws, role) for ws, role in pairs if ws.id == principal.api_key.workspace_id]
    return [workspace_out(ws, role) for ws, role in pairs]


@router.get("")
def list_workspaces(principal: PrincipalDep, repos: ReposDep) -> list[WorkspaceOut]:
    return visible_workspaces(principal, repos)


@router.post("", status_code=201)
def create(body: WorkspaceIn, principal: PrincipalDep, repos: ReposDep) -> WorkspaceOut:
    if principal.api_key is not None:
        raise HTTPException(403, "API keys cannot create workspaces")
    return workspace_out(create_workspace(repos, body.name.strip(), principal.user.id), "owner")


# --- members -----------------------------------------------------------------
@router.get("/{ws}/members")
def list_members(ctx: WorkspaceDep) -> list[MemberOut]:
    return [
        MemberOut(user_id=u.id, email=u.email, name=u.name, role=role)
        for u, role in ctx.repos.members_of(ctx.id)
    ]


@router.post("/{ws}/members", status_code=201)
def add_member(body: MemberIn, ctx: OwnerDep) -> MemberOut:
    user = ctx.repos.users.first(email=body.email.strip().lower())
    if user is None:
        raise HTTPException(404, "no user has signed up with that email")
    if ctx.repos.get_role(ctx.id, user.id) is not None:
        raise HTTPException(409, "user is already a member of this workspace")
    ctx.repos.add_member(ctx.id, user.id, body.role)
    return MemberOut(user_id=user.id, email=user.email, name=user.name, role=body.role)


@router.delete("/{ws}/members/{user_id}", status_code=204)
def remove_member(user_id: str, ctx: OwnerDep) -> None:
    members = ctx.repos.members_of(ctx.id)
    role = next((r for u, r in members if u.id == user_id), None)
    if role is None:
        raise HTTPException(404, "member not found")
    if role == "owner" and sum(1 for _, r in members if r == "owner") <= 1:
        raise HTTPException(409, "cannot remove the last owner of a workspace")
    ctx.repos.remove_member(ctx.id, user_id)
    for key in ctx.repos.api_keys.list(workspace_id=ctx.id, user_id=user_id):
        ctx.repos.api_keys.delete(key.id)


# --- api keys ----------------------------------------------------------------
def _key_out(key: ApiKey) -> dict:
    return key.model_dump(include={"id", "name", "prefix", "created_at", "last_used_at"})


@router.get("/{ws}/api-keys")
def list_api_keys(ctx: WorkspaceDep) -> list[ApiKeyOut]:
    return [ApiKeyOut(**_key_out(k)) for k in ctx.repos.api_keys.list(workspace_id=ctx.id)]


@router.post("/{ws}/api-keys", status_code=201)
def create_api_key(body: ApiKeyIn, ctx: WorkspaceDep) -> ApiKeyCreated:
    full, prefix, key_hash = generate_api_key()
    key = ctx.repos.api_keys.create(
        ApiKey(
            workspace_id=ctx.id,
            user_id=ctx.principal.user.id,
            name=body.name.strip(),
            prefix=prefix,
            key_hash=key_hash,
        )
    )
    return ApiKeyCreated(**_key_out(key), key=full)


@router.delete("/{ws}/api-keys/{key_id}", status_code=204)
def delete_api_key(key_id: str, ctx: WorkspaceDep) -> None:
    key = ctx.repos.api_keys.get(key_id)
    if key is None or key.workspace_id != ctx.id:
        raise HTTPException(404, "API key not found")
    if ctx.role != "owner" and key.user_id != ctx.principal.user.id:
        raise HTTPException(403, "only an owner can delete another member's API key")
    ctx.repos.api_keys.delete(key_id)


# --- summary -----------------------------------------------------------------
@router.get("/{ws}/summary")
def summary(ctx: WorkspaceDep) -> SummaryOut:
    repos = ctx.repos
    runs = repos.runs.list(workspace_id=ctx.id)
    by_status = {"queued": 0, "running": 0, "succeeded": 0, "failed": 0}
    for run in runs:
        by_status[run.status] = by_status.get(run.status, 0) + 1
    return SummaryOut(
        counts={
            "connections": len(repos.connections.list(workspace_id=ctx.id)),
            "actions": len(repos.actions.list(workspace_id=ctx.id)),
            "operators": len(repos.operators.list(workspace_id=ctx.id)),
            "schedules": len(repos.schedules.list(workspace_id=ctx.id)),
            "agents": len(repos.agents.list(workspace_id=ctx.id)),
            "runs": len(runs),
        },
        runs_by_status=by_status,
        recent_runs=[run_out(r) for r in runs[:10]],
        graph=repos.store.count_by_label(ctx.graph),
    )
