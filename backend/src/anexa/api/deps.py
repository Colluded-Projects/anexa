from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException

from ..models import ApiKey, Role, User, Workspace, utcnow
from ..repos import Repos
from ..security import API_KEY_PREFIX, decode_access_token, hash_api_key


def get_repos() -> Repos:
    return Repos()


ReposDep = Annotated[Repos, Depends(get_repos)]


@dataclass
class Principal:
    user: User
    via: Literal["bearer", "api_key"]
    api_key: ApiKey | None = None


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(401, detail, headers={"WWW-Authenticate": "Bearer"})


def _from_api_key(repos: Repos, raw: str) -> Principal:
    key = repos.api_keys.first(key_hash=hash_api_key(raw))
    user = repos.users.get(key.user_id) if key else None
    # A key stops working as soon as its creator leaves the workspace.
    if key is None or user is None or repos.get_role(key.workspace_id, user.id) is None:
        raise _unauthorized("invalid API key")
    key = repos.api_keys.update(key.id, last_used_at=utcnow())
    return Principal(user, "api_key", key)


def get_principal(
    repos: ReposDep,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Principal:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token.startswith(API_KEY_PREFIX):
            return _from_api_key(repos, token)
        user_id = decode_access_token(token, repos.settings)
        user = repos.users.get(user_id) if user_id else None
        if user is None:
            raise _unauthorized("invalid or expired token")
        return Principal(user, "bearer")
    if x_api_key:
        return _from_api_key(repos, x_api_key.strip())
    raise _unauthorized("not authenticated")


PrincipalDep = Annotated[Principal, Depends(get_principal)]


@dataclass
class WorkspaceCtx:
    workspace: Workspace
    role: Role
    principal: Principal
    repos: Repos

    @property
    def id(self) -> str:
        return self.workspace.id

    @property
    def graph(self) -> str:
        """Name of this workspace's company graph."""
        return self.repos.company_graph(self.workspace.id)


def get_workspace(ws: str, principal: PrincipalDep, repos: ReposDep) -> WorkspaceCtx:
    if principal.api_key is not None and principal.api_key.workspace_id != ws:
        raise HTTPException(403, "this API key belongs to a different workspace")
    workspace = repos.workspaces.get(ws)
    if workspace is None:
        raise HTTPException(404, "workspace not found")
    role = repos.get_role(ws, principal.user.id)
    if role is None:
        raise HTTPException(403, "not a member of this workspace")
    return WorkspaceCtx(workspace, role, principal, repos)


WorkspaceDep = Annotated[WorkspaceCtx, Depends(get_workspace)]


def require_owner(ctx: WorkspaceDep) -> WorkspaceCtx:
    if ctx.role != "owner":
        raise HTTPException(403, "owner role required")
    return ctx


OwnerDep = Annotated[WorkspaceCtx, Depends(require_owner)]
