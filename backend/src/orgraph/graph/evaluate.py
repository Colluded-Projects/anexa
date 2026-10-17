"""Score a linked graph against the demo company's gold links."""

from __future__ import annotations

from ..store import GraphStore
from .demo import GOLD, UNORDERED

# Which edges count as an answer for each gold category.
_EDGE_FOR = {
    "same_person": "SAME_AS",
    "references": "REFERENCES",
    "related": "RELATED_TO",
}


def found_links(store: GraphStore, graph: str) -> dict[str, set[tuple[str, ...]]]:
    """The linker's answers, as node keys, in the same shape as GOLD."""
    key = {n.id: n.props.get("key", n.id) for n in store.find_nodes(graph)}
    found: dict[str, set[tuple[str, ...]]] = {name: set() for name in GOLD}
    for edge in store.edges(graph):
        pair = (key[edge.src], key[edge.dst])
        for name, type in _EDGE_FOR.items():
            if edge.type == type:
                found[name].add(tuple(sorted(pair)) if name in UNORDERED else pair)
        if edge.type == "SOURCED_FROM":
            found["decisions"].add((pair[1],))
    return found


def score(store: GraphStore, graph: str) -> dict[str, dict[str, float | int]]:
    """Precision and recall per category. Precision is 1.0 when nothing was found."""
    found = found_links(store, graph)
    result: dict[str, dict[str, float | int]] = {}
    for name, gold in GOLD.items():
        expected = {tuple(sorted(p)) for p in gold} if name in UNORDERED else gold
        hits = len(found[name] & expected)
        result[name] = {
            "expected": len(expected),
            "found": len(found[name]),
            "correct": hits,
            "precision": round(hits / len(found[name]), 2) if found[name] else 1.0,
            "recall": round(hits / len(expected), 2),
        }
    return result
