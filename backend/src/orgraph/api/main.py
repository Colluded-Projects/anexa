from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.routing import Route

from .. import __version__
from ..config import get_settings
from ..repos import Repos
from ..security import hash_api_key
from ..store import NotFound, StoreError
from .routers import (
    actions,
    agents,
    auth,
    connections,
    graph,
    operators,
    runs,
    schedules,
    workspaces,
)

log = logging.getLogger(__name__)


def _api_key_is_valid(raw: str) -> bool:
    repos = Repos()
    key = repos.api_keys.first(key_hash=hash_api_key(raw))
    return key is not None and repos.get_role(key.workspace_id, key.user_id) is not None


def create_app() -> FastAPI:
    settings = get_settings()

    # Imported here so the MCP SDK is only loaded when the app is built.
    from ..mcp_server.http import MCP_PATH, build_mcp_http

    mcp_app, mcp_lifespan = build_mcp_http(_api_key_is_valid, settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_lifespan():
            yield

    app = FastAPI(title="Orgraph", version=__version__, lifespan=lifespan)
    # MCP over HTTP for Claude Code, authenticated with a workspace API key.
    app.router.routes.append(Route(MCP_PATH, mcp_app))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(NotFound)
    def not_found(request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "not found"}, status_code=404)

    @app.exception_handler(StoreError)
    def store_conflict(request: Request, exc: StoreError) -> JSONResponse:
        return JSONResponse({"detail": str(exc) or "storage conflict"}, status_code=409)

    @app.exception_handler(Exception)
    def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    for module in (auth, workspaces, actions, agents, graph, operators, runs, schedules):
        app.include_router(module.router)
    app.include_router(connections.catalog_router)
    app.include_router(connections.router)
    return app


app = create_app()


def run() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("orgraph.api.main:app", host=settings.api_host, port=settings.api_port)
