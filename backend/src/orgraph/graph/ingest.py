from __future__ import annotations

import re

from ..connectors.base import GraphDelta
from ..models import utcnow
from ..store import GraphStore
from .ontology import EDGE_TYPES, NODE_LABELS

# FalkorDB property names are identifiers; anything else is folded to "_".
_PROP_NAME = re.compile(r"[^A-Za-z0-9_]")


def apply_delta(store: GraphStore, graph: str, delta: GraphDelta, source: str) -> dict[str, int]:
    """Merge a connector's findings into a company graph. Nodes are matched on
    (label, key); edges whose endpoints are not in the graph are skipped.
    Returns counts of what was written."""
    ids: dict[tuple[str, str], str] = {}
    now = utcnow()
    skipped = 0

    for node in delta.nodes:
        if node.label not in NODE_LABELS:
            skipped += 1
            continue
        # A connector must not be able to overwrite a node's identity.
        props = {
            _PROP_NAME.sub("_", k): v
            for k, v in node.props.items()
            if v is not None and k not in ("id", "key")
        }
        stored = store.upsert_node(
            graph, node.label, {"key": node.key}, {**props, "source": source, "updated_at": now}
        )
        if not stored.props.get("name"):
            # Only a nameless node falls back to its key; never clobber a known name.
            store.update_node(graph, stored.id, {"name": node.key})
        ids[(node.label, node.key)] = stored.id

    def resolve(label: str, key: str) -> str | None:
        if (label, key) not in ids:
            found = store.find_nodes(graph, label, {"key": key}, limit=1)
            if not found:
                return None
            ids[(label, key)] = found[0].id
        return ids[(label, key)]

    edges = 0
    for edge in delta.edges:
        src = resolve(edge.src_label, edge.src_key)
        dst = resolve(edge.dst_label, edge.dst_key)
        if edge.type not in EDGE_TYPES or src is None or dst is None:
            skipped += 1
            continue
        store.create_edge(graph, src, edge.type, dst, {**edge.props, "source": source})
        edges += 1

    nodes = sum(1 for n in delta.nodes if n.label in NODE_LABELS)
    return {"nodes": nodes, "edges": edges, "skipped": skipped}
