from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from ...config import get_settings
from ...models import User, Workspace
from ...repos import Repos
from ...security import create_access_token, hash_password, verify_password
from ..common import user_out, workspace_out
from ..deps import PrincipalDep, ReposDep
from ..schemas import LoginIn, LoginOut, MeOut, SignupIn, SignupOut

router = APIRouter(prefix="/api", tags=["auth"])


def unique_slug(repos: Repos, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "workspace"
    slug, n = base, 1
    while repos.workspaces.first(slug=slug) is not None:
        n += 1
        slug = f"{base}-{n}"
    return slug


def create_workspace(repos: Repos, name: str, owner_id: str) -> Workspace:
    workspace = repos.workspaces.create(Workspace(name=name, slug=unique_slug(repos, name)))
    repos.add_member(workspace.id, owner_id, "owner")
    return workspace


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "store": get_settings().store_backend}


@router.post("/auth/signup", status_code=201)
def signup(body: SignupIn, repos: ReposDep) -> SignupOut:
    email = body.email.strip().lower()
    if repos.users.first(email=email) is not None:
        raise HTTPException(409, "an account with this email already exists")
    name = body.name.strip()
    user = repos.users.create(
        User(email=email, name=name, password_hash=hash_password(body.password))
    )
    ws_name = (body.workspace_name or "").strip() or f"{name or email.split('@')[0]}'s workspace"
    workspace = create_workspace(repos, ws_name, user.id)
    return SignupOut(
        access_token=create_access_token(user.id, repos.settings),
        user=user_out(user),
        workspace=workspace_out(workspace, "owner"),
    )


@router.post("/auth/login")
def login(body: LoginIn, repos: ReposDep) -> LoginOut:
    user = repos.users.first(email=body.email.strip().lower())
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "incorrect email or password")
    return LoginOut(access_token=create_access_token(user.id, repos.settings), user=user_out(user))


@router.get("/me")
def me(principal: PrincipalDep, repos: ReposDep) -> MeOut:
    from .workspaces import visible_workspaces

    return MeOut(user=user_out(principal.user), workspaces=visible_workspaces(principal, repos))
