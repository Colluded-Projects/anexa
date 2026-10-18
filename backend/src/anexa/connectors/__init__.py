from __future__ import annotations

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

__all__ = [
    "Connector",
    "ConnectorContext",
    "ConnectorError",
    "ConnectorSpec",
    "EdgeUpsert",
    "FieldSpec",
    "GraphDelta",
    "NodeUpsert",
    "OperationResult",
    "OperationSpec",
    "all_specs",
    "get_connector",
    "register",
]

_registry: dict[str, Connector] = {}
_loaded = False


def register(connector: Connector) -> Connector:
    _registry[connector.spec.key] = connector
    return connector


def _load_builtin() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import agent, github, google, jira, slack  # noqa: F401  (register on import)


def get_connector(key: str) -> Connector:
    _load_builtin()
    try:
        return _registry[key]
    except KeyError:
        raise ConnectorError(f"unknown connector {key!r}") from None


def all_specs() -> list[ConnectorSpec]:
    _load_builtin()
    return [c.spec for c in sorted(_registry.values(), key=lambda c: c.spec.title)]
