"""Rules linker: no AI, only exact names, ids found in text and shared words.

Runs in order, each rule building on the edges of the ones before:
same_person -> references -> related (+ topics) -> decisions -> knows_about.
Writing is idempotent: edges are upserted and Topic/Decision nodes are keyed.
"""

from __future__ import annotations

import re
from collections import Counter
from itertools import combinations
from typing import Any

from ...store import GraphStore, Node
from . import write_link

ITEM_LABELS = ("Message", "Ticket", "Document")

# Pairs of items sharing at least this share of their keywords are RELATED_TO.
# Tuned on the demo company: 0.35 keeps the strong login/invoice pairs and
# drops most of the many weak "kafka event" pairs.
RELATED_THRESHOLD = 0.35

STOPWORDS = {
    "about", "after", "again", "also", "been", "being", "from", "have", "here",
    "into", "just", "keep", "like", "need", "only", "should", "some", "than",
    "that", "their", "them", "then", "there", "they", "this", "were", "what",
    "when", "will", "with", "would", "your",
}

JIRA_KEY = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
GITHUB_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/(?:pull|issues)/(\d+)")
GITHUB_REF = re.compile(r"\b([\w.-]+)/([\w.-]+)#(\d+)")
GOOGLE_DOC = re.compile(r"docs\.google\.com/document/d/([\w-]+)")

DECISION_PHRASES = ("we decided", "we go with", "agreed to")

# Person -> item edges, and item -> Person edges, that make someone involved.
PERSON_TO_ITEM = ("AUTHORED", "OWNS")
ITEM_TO_PERSON = ("ASSIGNED_TO",)


def link_rules(store: GraphStore, graph: str) -> dict[str, int]:
    links: dict[str, int] = {}
    for rule in (same_person, references, related, decisions, knows_about):
        links.update(rule(store, graph))
    return links


def _items(store: GraphStore, graph: str) -> list[Node]:
    return [n for label in ITEM_LABELS for n in store.find_nodes(graph, label)]


def _text(node: Node) -> str:
    return f"{node.props.get('name', '')} {node.props.get('text', '')}"


# ---- 1. same person ---------------------------------------------------------


def _normal(name: str) -> str:
    return " ".join(name.lower().split())


def same_person(store: GraphStore, graph: str) -> dict[str, int]:
    """Person without email -> SAME_AS -> Person with email, by name."""
    people = store.find_nodes(graph, "Person")
    canonical = [p for p in people if p.props.get("email")]
    count = 0
    for other in people:
        if other.props.get("email"):
            continue
        name = _normal(other.props["name"])
        for person in canonical:
            full = _normal(person.props["name"])
            first, last = full.split(" ")[0], full.split(" ")[-1]
            if name == full:
                confidence = 0.8
            elif name.split(" ") == [first, last[0] + "."]:
                confidence = 0.6
            else:
                continue
            write_link(
                store, graph, other.id, "SAME_AS", person.id,
                method="name", confidence=confidence, evidence=f"{other.props['name']} ~ {full}",
            )
            count += 1
    return {"SAME_AS": count}


# ---- 2. references ----------------------------------------------------------


def _referenced_keys(text: str) -> list[tuple[str, str]]:
    """(node key, matched snippet) for every id found in `text`."""
    found = [(f"jira:issue:{m.group(0)}", m.group(0)) for m in JIRA_KEY.finditer(text)]
    for pattern in (GITHUB_URL, GITHUB_REF):
        found += [
            (f"github:issue:{m[1]}/{m[2]}#{m[3]}", m.group(0)) for m in pattern.finditer(text)
        ]
    found += [(f"google:file:{m[1]}", m.group(0)) for m in GOOGLE_DOC.finditer(text)]
    return found


def references(store: GraphStore, graph: str) -> dict[str, int]:
    by_key = {n.props["key"]: n for n in store.find_nodes(graph)}
    written: set[tuple[str, str]] = set()
    for item in _items(store, graph):
        for key, snippet in _referenced_keys(_text(item)):
            target = by_key.get(key)
            if target is None or target.id == item.id or (item.id, target.id) in written:
                continue
            write_link(
                store, graph, item.id, "REFERENCES", target.id,
                method="regex", confidence=1.0, evidence=snippet,
            )
            written.add((item.id, target.id))
    return {"REFERENCES": len(written)}


# ---- 3. related + topics ----------------------------------------------------


def keywords(text: str) -> set[str]:
    """Lowercase words of 4+ letters, minus stopwords and URLs, trailing "s" stripped."""
    text = re.sub(r"https?://\S+", " ", text.lower())
    words = {w.removesuffix("s") for w in re.findall(r"[a-z]+", text) if len(w) >= 4}
    return words - STOPWORDS


def related(store: GraphStore, graph: str) -> dict[str, int]:
    items = _items(store, graph)
    words = {item.id: keywords(_text(item)) for item in items}
    referenced = {(e.src, e.dst) for e in store.edges(graph, type="REFERENCES")}

    count = 0
    for a, b in combinations(items, 2):
        shared = words[a.id] & words[b.id]
        if not shared or (a.id, b.id) in referenced or (b.id, a.id) in referenced:
            continue
        jaccard = len(shared) / len(words[a.id] | words[b.id])
        if jaccard >= RELATED_THRESHOLD:
            write_link(
                store, graph, a.id, "RELATED_TO", b.id,
                method="keywords", confidence=round(jaccard, 2), evidence=", ".join(sorted(shared)),
            )
            count += 1

    usage = Counter(w for item_words in words.values() for w in item_words)
    about = 0
    for word in sorted(w for w, n in usage.items() if n >= 2):
        topic = store.upsert_node(
            graph, "Topic", {"key": f"topic:{word}"}, {"name": word, "source": "linker"}
        )
        for item in items:
            if word in words[item.id]:
                write_link(
                    store, graph, item.id, "ABOUT", topic.id, method="keywords", confidence=1.0
                )
                about += 1
    return {"RELATED_TO": count, "ABOUT": about}


# ---- 4. decisions -----------------------------------------------------------


def _is_decision(text: str) -> bool:
    lower = text.lower()
    return text.startswith("Decision:") or any(p in lower for p in DECISION_PHRASES)


def decisions(store: GraphStore, graph: str) -> dict[str, int]:
    counts = Counter({"SOURCED_FROM": 0, "DECIDED": 0, "AFFECTS": 0})
    for item in _items(store, graph):
        text = item.props.get("text", "")
        if not _is_decision(text):
            continue
        decision = store.upsert_node(
            graph, "Decision", {"key": f"decision:{item.props['key']}"},
            {"name": text[:80], "source": "linker"},
        )
        link: dict[str, Any] = {"method": "phrase", "confidence": 1.0}
        write_link(store, graph, decision.id, "SOURCED_FROM", item.id, **link, evidence=text[:80])
        counts["SOURCED_FROM"] += 1
        for edge in store.edges(graph, item.id, direction="in"):
            if edge.type in PERSON_TO_ITEM:
                write_link(store, graph, edge.src, "DECIDED", decision.id, **link)
                counts["DECIDED"] += 1
        for edge in store.edges(graph, item.id, type="REFERENCES", direction="out"):
            write_link(store, graph, decision.id, "AFFECTS", edge.dst, **link)
            counts["AFFECTS"] += 1
    return dict(counts)


# ---- 5. who knows what ------------------------------------------------------


def _canonical(store: GraphStore, graph: str) -> dict[str, str]:
    """Person id -> the id of the person it is SAME_AS (or itself)."""
    people = {p.id: p.id for p in store.find_nodes(graph, "Person")}
    for edge in store.edges(graph, type="SAME_AS"):
        people[edge.src] = edge.dst
    return people


def knows_about(store: GraphStore, graph: str) -> dict[str, int]:
    canonical = _canonical(store, graph)
    involved: set[tuple[str, str]] = set()  # (canonical person id, item id)
    for edge in store.edges(graph):
        if edge.type in PERSON_TO_ITEM and edge.src in canonical:
            involved.add((canonical[edge.src], edge.dst))
        if edge.type in ITEM_TO_PERSON and edge.dst in canonical:
            involved.add((canonical[edge.dst], edge.src))

    topics_of: dict[str, list[str]] = {}
    for edge in store.edges(graph, type="ABOUT"):
        topics_of.setdefault(edge.src, []).append(edge.dst)
    score = Counter(
        (person, topic) for person, item in involved for topic in topics_of.get(item, [])
    )

    for (person, topic), n in score.items():
        write_link(store, graph, person, "KNOWS_ABOUT", topic, method="activity", confidence=n)
    return {"KNOWS_ABOUT": len(score)}


def experts(store: GraphStore, graph: str, topic_word: str) -> list[dict[str, Any]]:
    """People who know about `topic_word`, best first."""
    topics = store.find_nodes(graph, "Topic", {"key": f"topic:{topic_word.lower()}"})
    if not topics:
        return []
    people = {p.id: p for p in store.find_nodes(graph, "Person")}
    found = [
        {
            "name": people[e.src].props["name"],
            "key": people[e.src].props["key"],
            "score": e.props["confidence"],
        }
        for e in store.edges(graph, topics[0].id, type="KNOWS_ABOUT", direction="in")
    ]
    return sorted(found, key=lambda e: (-e["score"], e["name"]))
