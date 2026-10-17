"""Linker: connects what the connectors wrote separately (same person across
systems, items that reference or talk about each other, decisions).

Every edge it writes carries `method`, `confidence` and optional `evidence`
so answers can show why two things are linked. Each branch of the project
plugs in a different strategy behind `link_graph`.
"""

from __future__ import annotations

from typing import Any

from ...config import get_settings
from ...store import Edge, GraphStore

STRATEGY = "hybrid"


def write_link(
    store: GraphStore,
    graph: str,
    src: str,
    type: str,
    dst: str,
    *,
    method: str,
    confidence: float,
    evidence: str | None = None,
) -> Edge:
    props: dict[str, Any] = {"source": "linker", "method": method, "confidence": confidence}
    if evidence:
        props["evidence"] = evidence[:300]
    return store.create_edge(graph, src, type, dst, props)


def link_graph(store: GraphStore, graph: str) -> dict[str, Any]:
    """Find and write links: rules first, then Claude when settings.llm_enabled.
    Returns {"strategy": ..., "links": {edge type: count}, "llm": "on" | "off"}."""
    from . import llm
    from .rules import link_rules  # both import write_link from here

    links = link_rules(store, graph)
    if not get_settings().llm_enabled:
        return {"strategy": STRATEGY, "links": links, "llm": "off"}
    for type, count in llm.link_llm(store, graph, llm.ask_claude).items():
        links[type] = links.get(type, 0) + count
    return {"strategy": STRATEGY, "links": links, "llm": "on"}
