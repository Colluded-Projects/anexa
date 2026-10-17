"""The AI half of the linker: Claude proposes links, plain code validates them."""

import json

from orgraph.config import get_settings
from orgraph.graph import demo
from orgraph.graph.evaluate import score
from orgraph.graph.linking import STRATEGY, link_graph, llm
from orgraph.graph.linking.llm import SCHEMA, link_llm

G = "ws_demo"

ANSWER = {
    "same_person": [
        # good
        {"a": demo.JIRA_CAROL, "b": demo.CAROL, "reason": "Carol D. is Carol Diaz",
         "confidence": 0.6},
        {"a": demo.GH_ADA, "b": demo.ADA, "reason": "same name", "confidence": 1.5},
        # bad: unknown key, Person <-> Ticket, self link
        {"a": "jira:user:zz", "b": demo.DAN, "reason": "?", "confidence": 0.9},
        {"a": demo.DAN, "b": demo.BILL3, "reason": "assigned", "confidence": 0.9},
        {"a": demo.BOB, "b": demo.BOB, "reason": "self", "confidence": 0.9},
    ],
    "related": [
        # good: quote is in M3's text (different case)
        {"a": demo.M3, "b": demo.API7, "quote": "Rate limiting on the login", "confidence": 0.8},
        # good: quote is in b's text
        {"a": demo.M4, "b": demo.BILL3, "quote": "empty CSV file", "confidence": 0.9},
        # bad: invented quote, self link, unknown key
        {"a": demo.M3, "b": demo.ENG15, "quote": "ship it on friday", "confidence": 0.9},
        {"a": demo.M1, "b": demo.M1, "quote": "Kafka", "confidence": 0.9},
        {"a": demo.M1, "b": "google:file:nope", "quote": "Kafka", "confidence": 0.9},
    ],
    "decisions": [
        {
            "source": demo.M2,
            "summary": "Use Kafka for the event bus",
            "quote": "we go with Kafka",
            "decided_by": [demo.BOB],
            "affects": [demo.ENG12],
            "confidence": 0.9,
        },
        # bad: quote not in the source
        {
            "source": demo.ADR4,
            "summary": "Use RabbitMQ",
            "quote": "adopt RabbitMQ",
            "decided_by": [demo.BOB],
            "affects": [],
            "confidence": 0.9,
        },
        # bad: unknown key in affects
        {
            "source": demo.M1,
            "summary": "Kafka",
            "quote": "move the event bus to Kafka",
            "decided_by": [demo.ADA],
            "affects": ["jira:issue:NOPE-1"],
            "confidence": 0.9,
        },
    ],
}


def fake_ask(prompts):
    def ask(prompt):
        prompts.append(prompt)
        return ANSWER

    return ask


def by_key(store):
    return {n.props["key"]: n for n in store.find_nodes(G)}


def linked(store):
    key = {n.id: n.props["key"] for n in store.find_nodes(G)}
    return {
        (key[e.src], e.type, key[e.dst]): e.props
        for e in store.edges(G)
        if e.props.get("source") == "linker"
    }


def test_only_valid_links_are_written(store):
    demo.load(store, G)
    counts = link_llm(store, G, fake_ask([]))

    decision = f"decision:{demo.M2}"
    assert set(linked(store)) == {
        (demo.JIRA_CAROL, "SAME_AS", demo.CAROL),
        (demo.GH_ADA, "SAME_AS", demo.ADA),
        (demo.M3, "RELATED_TO", demo.API7),
        (demo.M4, "RELATED_TO", demo.BILL3),
        (decision, "SOURCED_FROM", demo.M2),
        (demo.BOB, "DECIDED", decision),
        (decision, "AFFECTS", demo.ENG12),
    }
    assert counts == {"SAME_AS": 2, "RELATED_TO": 2, "SOURCED_FROM": 1, "DECIDED": 1, "AFFECTS": 1}
    assert by_key(store)[decision].label == "Decision"
    assert by_key(store)[decision].props["name"] == "Use Kafka for the event bus"


def test_links_carry_provenance(store):
    demo.load(store, G)
    link_llm(store, G, fake_ask([]))
    links = linked(store)

    carol = links[(demo.JIRA_CAROL, "SAME_AS", demo.CAROL)]
    assert carol == {
        "source": "linker", "method": "llm", "confidence": 0.6, "evidence": "Carol D. is Carol Diaz"
    }
    assert links[(demo.GH_ADA, "SAME_AS", demo.ADA)]["confidence"] == 1.0  # clipped
    assert links[(demo.M3, "RELATED_TO", demo.API7)]["evidence"] == "Rate limiting on the login"
    assert links[(f"decision:{demo.M2}", "SOURCED_FROM", demo.M2)]["evidence"] == "we go with Kafka"


def test_score_improves(store):
    demo.load(store, G)
    link_llm(store, G, fake_ask([]))
    result = score(store, G)
    assert result["same_person"]["correct"] == 2 and result["same_person"]["precision"] == 1.0
    assert result["related"]["correct"] == 2 and result["related"]["precision"] == 1.0
    assert result["decisions"]["correct"] == 1


def test_prompt_lists_nodes_and_existing_links(store):
    demo.load(store, G)
    prompts = []
    link_llm(store, G, fake_ask(prompts))
    assert len(prompts) == 1
    assert demo.JIRA_CAROL in prompts[0] and demo.M3 in prompts[0] and demo.RFC1 in prompts[0]
    assert "rate limiting on the login endpoint" in prompts[0]
    # an existing connector edge, so Claude doesn't propose it again
    assert f"{demo.BOB} AUTHORED {demo.M2}" in prompts[0]


def test_rerun_is_idempotent(store):
    demo.load(store, G)
    link_llm(store, G, fake_ask([]))
    edges, nodes = len(store.edges(G)), len(store.find_nodes(G))
    link_llm(store, G, fake_ask([]))
    assert (len(store.edges(G)), len(store.find_nodes(G))) == (edges, nodes)


def test_schema_requires_every_field():
    decision = SCHEMA["properties"]["decisions"]["items"]
    assert decision["additionalProperties"] is False
    assert set(decision["required"]) == set(decision["properties"])
    assert set(SCHEMA["required"]) == {"same_person", "related", "decisions"}
    json.dumps(SCHEMA)


def test_link_graph_skips_llm_when_disabled(store, settings):
    demo.load(store, G)
    stats = link_graph(store, G)
    assert stats == {"strategy": STRATEGY, "links": {}, "llm": "off"}
    assert STRATEGY == "hybrid"


def test_link_graph_uses_claude_when_enabled(store, monkeypatch):
    monkeypatch.setenv("ORGRAPH_LLM_ENABLED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(llm, "ask_claude", fake_ask([]))
    demo.load(store, G)
    stats = link_graph(store, G)
    get_settings.cache_clear()
    assert stats["llm"] == "on"
    assert stats["links"]["SAME_AS"] == 2


def test_settings_defaults(settings):
    assert settings.llm_enabled is False
    assert settings.llm_model == "claude-opus-5"
