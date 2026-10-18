from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from ... import connectors
from ...connectors.base import Connector, ConnectorContext, ConnectorError, ConnectorSpec
from ...models import Connection
from ...security import decrypt_secrets, encrypt_secrets
from ..common import invalid, scoped
from ..deps import PrincipalDep, WorkspaceDep
from ..schemas import ConnectionIn, ConnectionOut, ConnectionPatch, ConnectionTestOut

log = logging.getLogger(__name__)

catalog_router = APIRouter(prefix="/api", tags=["connectors"])
router = APIRouter(prefix="/api/workspaces/{ws}/connections", tags=["connections"])


@catalog_router.get("/connectors")
def catalog(principal: PrincipalDep) -> list[ConnectorSpec]:
    return connectors.all_specs()


def connector_or_422(key: str) -> Connector:
    try:
        return connectors.get_connector(key)
    except ConnectorError as exc:
        raise invalid(str(exc)) from exc


def _out(conn: Connection) -> ConnectionOut:
    return ConnectionOut(**conn.model_dump(exclude={"workspace_id", "secrets_enc"}))


def _split(
    spec: ConnectorSpec, config: dict[str, Any], secrets: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Route each declared field to where the spec says it lives, whichever
    object the client sent it in. Undeclared fields stay where they were sent."""
    secret_names = {f.name for f in spec.config_fields if f.secret}
    plain_names = {f.name for f in spec.config_fields if not f.secret}
    out_config = {k: v for k, v in config.items() if k not in secret_names}
    out_secrets = {k: v for k, v in secrets.items() if k not in plain_names}
    out_secrets.update({k: v for k, v in config.items() if k in secret_names})
    out_config.update({k: v for k, v in secrets.items() if k in plain_names})
    return out_config, out_secrets


def _check_required(spec: ConnectorSpec, config: dict[str, Any], secrets: dict[str, Any]) -> None:
    missing = [
        f.name
        for f in spec.config_fields
        if f.required
        and f.default is None
        and (secrets if f.secret else config).get(f.name) in (None, "")
    ]
    if missing:
        raise invalid(f"missing required fields: {', '.join(missing)}")


def _stored_secrets(conn: Connection, ctx: WorkspaceDep) -> dict[str, Any]:
    try:
        return decrypt_secrets(conn.secrets_enc, ctx.repos.settings)
    except ValueError as exc:
        raise HTTPException(409, f"{exc}; re-enter this connection's secrets") from exc


@router.get("")
def list_connections(ctx: WorkspaceDep) -> list[ConnectionOut]:
    return [_out(c) for c in ctx.repos.connections.list(workspace_id=ctx.id)]


@router.post("", status_code=201)
def create(body: ConnectionIn, ctx: WorkspaceDep) -> ConnectionOut:
    spec = connector_or_422(body.connector).spec
    config, secrets = _split(spec, body.config, body.secrets)
    secrets = {k: v for k, v in secrets.items() if v not in (None, "")}
    _check_required(spec, config, secrets)
    conn = ctx.repos.connections.create(
        Connection(
            workspace_id=ctx.id,
            name=body.name.strip(),
            connector=spec.key,
            config=config,
            secrets_enc=encrypt_secrets(secrets, ctx.repos.settings),
            secret_fields=sorted(secrets),
        )
    )
    return _out(conn)


@router.get("/{connection_id}")
def get(connection_id: str, ctx: WorkspaceDep) -> ConnectionOut:
    return _out(scoped(ctx.repos.connections, connection_id, ctx, "connection"))


@router.patch("/{connection_id}")
def update(connection_id: str, body: ConnectionPatch, ctx: WorkspaceDep) -> ConnectionOut:
    conn = scoped(ctx.repos.connections, connection_id, ctx, "connection")
    sent = body.model_dump(exclude_unset=True)
    changes: dict[str, Any] = {}
    if sent.get("name") is not None:
        changes["name"] = sent["name"].strip()

    if sent.get("config") is not None or sent.get("secrets") is not None:
        spec = connector_or_422(conn.connector).spec
        new_config = sent["config"] if sent.get("config") is not None else conn.config
        new_config, patch_secrets = _split(spec, new_config, sent.get("secrets") or {})
        secrets = _stored_secrets(conn, ctx) if patch_secrets or conn.secret_fields else {}
        for name, value in patch_secrets.items():
            if value in (None, ""):
                secrets.pop(name, None)
            else:
                secrets[name] = value
        _check_required(spec, new_config, secrets)
        changes.update(
            config=new_config,
            secrets_enc=encrypt_secrets(secrets, ctx.repos.settings),
            secret_fields=sorted(secrets),
            status="untested",
            status_detail="",
        )
    return _out(ctx.repos.connections.update(conn.id, **changes) if changes else conn)


@router.delete("/{connection_id}", status_code=204)
def delete(connection_id: str, ctx: WorkspaceDep) -> None:
    conn = scoped(ctx.repos.connections, connection_id, ctx, "connection")
    users = ctx.repos.actions.list(workspace_id=ctx.id, connection_id=conn.id)
    if users:
        names = ", ".join(a.name for a in users[:5])
        raise HTTPException(409, f"connection is used by {len(users)} action(s): {names}")
    ctx.repos.connections.delete(conn.id)


@router.post("/{connection_id}/test")
def test(connection_id: str, ctx: WorkspaceDep) -> ConnectionTestOut:
    conn = scoped(ctx.repos.connections, connection_id, ctx, "connection")
    identity: dict[str, Any] = {}
    try:
        connector = connectors.get_connector(conn.connector)
        secrets = decrypt_secrets(conn.secrets_enc, ctx.repos.settings)
        timeout = ctx.repos.settings.connector_timeout_seconds
        with httpx.Client(timeout=timeout, follow_redirects=True) as http:
            identity = connector.test(ConnectorContext(dict(conn.config), secrets, http)) or {}
        ok, detail = True, "Connection verified"
    except (ConnectorError, ValueError) as exc:
        ok, detail = False, str(exc)
    except httpx.HTTPError as exc:
        ok, detail = False, f"could not reach the service: {exc}"
    except Exception as exc:  # a connector bug must not turn the test into a 500
        log.exception("connection test crashed for %s", conn.id)
        ok, detail = False, f"unexpected error: {exc}"
    ctx.repos.connections.update(
        conn.id, status="ok" if ok else "error", status_detail="" if ok else detail
    )
    return ConnectionTestOut(ok=ok, detail=detail, identity=identity)
