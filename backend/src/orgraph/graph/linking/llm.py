"""AI half of the linker: Claude reads a catalog of the graph and proposes
links; plain code checks every proposal against the graph before writing it.

A proposal is dropped when a key is unknown, a same_person pair is not two
Person nodes, a quote is not really in the item's text, or it links a node to
itself.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from typing import Any

import anthropic

from ...config import get_settings
from ...store import GraphStore, Node
from . import write_link

Ask = Callable[[str], dict[str, Any]]

LABELS = ["Person", "Message", "Ticket", "Document"]
MAX_NODES = 200
TEXT_CHARS = 600
METHOD = "llm"


def _object(**fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def _list(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


_STR = {"type": "string"}
_NUM = {"type": "number"}

SCHEMA = _object(
    same_person=_list(_object(a=_STR, b=_STR, reason=_STR, confidence=_NUM)),
    related=_list(_object(a=_STR, b=_STR, quote=_STR, confidence=_NUM)),
    decisions=_list(
        _object(
            source=_STR,
            summary=_STR,
            quote=_STR,
            decided_by=_list(_STR),
            affects=_list(_STR),
            confidence=_NUM,
        )
    ),
)

PROMPT = """You link a company knowledge graph. Connectors wrote people, messages,
tickets and documents separately; find what belongs together.

Return JSON with:
- same_person: two Person keys that are one human (different accounts). Give a reason.
- related: two items about the same thing that are not linked yet. `quote` must be
  copied word for word from the text of `a` or `b`.
- decisions: a decision made in a message, ticket or document (`source`). `quote` must be
  copied word for word from the source's text. `decided_by` are Person keys, `affects`
  are keys of items the decision changes.
Use only keys from the catalog. confidence is 0..1. Do not repeat existing links.

Catalog (one JSON object per line):
{catalog}

Existing links:
{edges}
"""


def _text(node: Node) -> str:
    return f"{node.props.get('name', '')}\n{node.props.get('text', '')}"


def build_prompt(nodes: dict[str, Node], edges: list[str]) -> str:
    lines = [
        json.dumps(
            {
                "key": key,
                "label": node.label,
                "name": node.props.get("name", ""),
                "text": node.props.get("text", "")[:TEXT_CHARS],
            }
        )
        for key, node in nodes.items()
    ]
    return PROMPT.format(catalog="\n".join(lines), edges="\n".join(edges))


def ask_claude(prompt: str) -> dict[str, Any]:
    response = anthropic.Anthropic().beta.messages.create(
        model=get_settings().llm_model,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)


def _quoted(quote: str, *nodes: Node) -> bool:
    return any(quote.lower() in _text(node).lower() for node in nodes)


def _clip(confidence: float) -> float:
    return min(max(float(confidence), 0.0), 1.0)


def link_llm(store: GraphStore, graph: str, ask: Ask) -> dict[str, int]:
    """Ask Claude once for links, write the ones that pass validation.
    Returns {edge type: count written}."""
    nodes: dict[str, Node] = {}
    for label in LABELS:
        for node in store.find_nodes(graph, label):
            nodes[node.props["key"]] = node
    nodes = dict(list(nodes.items())[:MAX_NODES])

    key_of = {node.id: key for key, node in nodes.items()}
    edges = [
        f"{key_of[e.src]} {e.type} {key_of[e.dst]}"
        for e in store.edges(graph)
        if e.src in key_of and e.dst in key_of
    ]
    answer = ask(build_prompt(nodes, edges))

    counts: Counter[str] = Counter()

    def link(src: Node, type: str, dst: Node, confidence: float, evidence: str) -> None:
        write_link(
            store, graph, src.id, type, dst.id,
            method=METHOD, confidence=_clip(confidence), evidence=evidence,
        )
        counts[type] += 1

    for item in answer["same_person"]:
        a, b = nodes.get(item["a"]), nodes.get(item["b"])
        if a is None or b is None or a is b:
            continue
        if a.label != "Person" or b.label != "Person":
            continue
        link(a, "SAME_AS", b, item["confidence"], item["reason"])

    for item in answer["related"]:
        a, b = nodes.get(item["a"]), nodes.get(item["b"])
        if a is None or b is None or a is b:
            continue
        if not _quoted(item["quote"], a, b):
            continue
        link(a, "RELATED_TO", b, item["confidence"], item["quote"])

    for item in answer["decisions"]:
        source = nodes.get(item["source"])
        people = [nodes.get(key) for key in item["decided_by"]]
        affected = [nodes.get(key) for key in item["affects"]]
        if source is None or None in people or None in affected:
            continue
        if not _quoted(item["quote"], source):
            continue
        decision = store.upsert_node(
            graph,
            "Decision",
            {"key": f"decision:{item['source']}"},
            {"name": item["summary"], "text": item["quote"], "source": "linker"},
        )
        link(decision, "SOURCED_FROM", source, item["confidence"], item["quote"])
        for person in people:
            link(person, "DECIDED", decision, item["confidence"], item["quote"])
        for target in affected:
            link(decision, "AFFECTS", target, item["confidence"], item["quote"])

    return dict(counts)
