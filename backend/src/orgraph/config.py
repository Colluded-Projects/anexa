from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ORGRAPH_", env_file=".env", extra="ignore")

    # --- storage -----------------------------------------------------------
    # "falkor" talks to a FalkorDB server, "memory" is a process-local store
    # used by tests and single-process demos.
    store_backend: Literal["falkor", "memory"] = "falkor"
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_username: str | None = None
    falkordb_password: str | None = None
    # Graph holding platform data (users, connections, actions, operators, runs).
    system_graph: str = "orgraph_system"
    # Each workspace's company graph is named f"{company_graph_prefix}{workspace_id}".
    company_graph_prefix: str = "company_"

    # --- celery ------------------------------------------------------------
    # db 1 keeps Celery keys apart from the graphs when FalkorDB doubles as the broker.
    redis_url: str = "redis://localhost:6379/1"
    celery_result_backend: str | None = None
    # Run tasks inline in the calling process instead of sending them to a worker.
    celery_eager: bool = False
    scheduler_tick_seconds: int = 30

    # --- security ----------------------------------------------------------
    secret_key: str = "dev-secret-change-me"
    # urlsafe-base64 32 byte Fernet key; derived from secret_key when unset.
    encryption_key: str | None = None
    access_token_ttl_minutes: int = 60 * 24

    # --- http --------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173"]
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    connector_timeout_seconds: float = 20.0

    # --- mcp server (acts as a client of the REST API) -----------------------
    api_url: str = "http://127.0.0.1:8000"
    api_key: str | None = None

    # --- placeholders for the future agent layer (unused by the platform) ----
    openrouter_api_key: str | None = None
    jev_api_key: str | None = None

    def company_graph(self, workspace_id: str) -> str:
        return f"{self.company_graph_prefix}{workspace_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
