from __future__ import annotations

from ..config import get_settings
from .base import Direction, Edge, GraphStore, Node, NotFound, StoreError
from .memory import MemoryStore

__all__ = [
    "Direction",
    "Edge",
    "GraphStore",
    "MemoryStore",
    "Node",
    "NotFound",
    "StoreError",
    "get_store",
    "set_store",
]

_store: GraphStore | None = None


def get_store() -> GraphStore:
    """Process-wide store, built from settings on first use."""
    global _store
    if _store is None:
        settings = get_settings()
        if settings.store_backend == "memory":
            _store = MemoryStore()
        else:
            from .falkor import FalkorStore

            _store = FalkorStore.from_settings(settings)
    return _store


def set_store(store: GraphStore | None) -> None:
    """Override (or reset with None) the process-wide store. Used by tests."""
    global _store
    _store = store
