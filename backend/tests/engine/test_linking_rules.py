"""The rules linker: no AI, only names, ids in text and shared words."""

from orgraph.graph import demo
from orgraph.graph.evaluate import score
from orgraph.graph.linking import STRATEGY, link_graph
from orgraph.graph.linking.rules import (
    decisions,
    experts,
    keywords,
    knows_about,
    references,
    related,
    same_person,
)

G = "ws_rules"


def node(store, label, key, **props):
    return store.create_node(G, label, {"key": key, "name": key, **props})


def links(store, type):
    key = {n.id: n.props["key"] for n in store.find_nodes(G)}
    return {(key[e.src], key[e.dst]) for e in store.edges(G, type=type)}


# ---- on the demo company ----------------------------------------------------


def test_demo_scores(store):
    demo.load(store, G)
    stats = link_graph(store, G)
    assert stats["strategy"] == STRATEGY
    assert stats["links"]["REFERENCES"] == 7

    result = score(store, G)
    print(result)
    assert result["references"]["precision"] == 1.0 and result["references"]["recall"] == 1.0
    assert result["same_person"]["precision"] == 1.0 and result["same_person"]["recall"] >= 0.8
    assert result["decisions"]["recall"] == 1.0
    assert result["related"]["precision"] >= 0.5 and result["related"]["recall"] >= 0.4


def test_linking_twice_writes_no_extra_edges(store):
    demo.load(store, G)
    link_graph(store, G)
    edges, nodes = len(store.edges(G)), len(store.find_nodes(G))
    link_graph(store, G)
    assert len(store.edges(G)) == edges and len(store.find_nodes(G)) == nodes


def test_demo_experts_on_kafka(store):
    demo.load(store, G)
    link_graph(store, G)
    names = [e["name"] for e in experts(store, G, "kafka")]
    assert "Ada Lovelace" in names and "Bob Stone" in names
    assert experts(store, G, "Kafka")[0]["score"] >= experts(store, G, "kafka")[-1]["score"]


# ---- one small graph per rule -----------------------------------------------


def test_same_person_by_full_name_and_initial(store):
    node(store, "Person", "email:c@x.io", name="Carol Diaz", email="c@x.io")
    node(store, "Person", "gh:carol", name="  carol   DIAZ ")
    node(store, "Person", "jira:c", name="Carol D.")
    node(store, "Person", "jira:other", name="Carol Smith")
    assert same_person(store, G) == {"SAME_AS": 2}
    assert links(store, "SAME_AS") == {("gh:carol", "email:c@x.io"), ("jira:c", "email:c@x.io")}
    confidence = {e.props["confidence"] for e in store.edges(G, type="SAME_AS")}
    assert confidence == {0.8, 0.6}


def test_references_from_ids_in_text(store):
    node(store, "Ticket", "jira:issue:ENG-1", name="ENG-1: thing")
    node(store, "Ticket", "github:issue:o/r#3")
    node(store, "Document", "google:file:abc")
    node(
        store, "Message", "m1",
        text="see ENG-1, https://github.com/o/r/pull/3 and "
        "https://docs.google.com/document/d/abc/edit, not ENG-99",
    )
    node(store, "Message", "m2", text="o/r#3 again")
    assert references(store, G) == {"REFERENCES": 4}
    assert links(store, "REFERENCES") == {
        ("m1", "jira:issue:ENG-1"),
        ("m1", "github:issue:o/r#3"),
        ("m1", "google:file:abc"),
        ("m2", "github:issue:o/r#3"),
    }
    evidence = {e.props["evidence"] for e in store.edges(G, type="REFERENCES")}
    assert "ENG-1" in evidence and "o/r#3" in evidence


def test_keywords():
    assert keywords("The Bots keep hammering the login at https://x.io/login") == {
        "bot", "hammering", "login"
    }


def test_related_by_shared_words_and_topics(store):
    m1 = node(store, "Message", "m1", text="login rate limiting for bots")
    node(store, "Ticket", "t1", text="add rate limiting to login, bots")
    node(store, "Ticket", "t2", text="invoice export broken")
    d1 = node(store, "Document", "d1", text="login rate limiting for bots")
    store.create_edge(G, d1.id, "REFERENCES", m1.id)
    counts = related(store, G)
    pairs = {tuple(sorted(p)) for p in links(store, "RELATED_TO")}
    assert pairs == {("m1", "t1"), ("d1", "t1")}
    edge = store.edges(G, type="RELATED_TO")[0]
    assert 0 < edge.props["confidence"] <= 1 and "login" in edge.props["evidence"]
    assert {n.props["key"] for n in store.find_nodes(G, "Topic")} == {
        "topic:login", "topic:rate", "topic:limiting", "topic:bot"
    }
    assert counts == {"RELATED_TO": 2, "ABOUT": 12}


def test_decisions_from_phrases(store):
    bob = node(store, "Person", "bob")
    m1 = node(store, "Message", "m1", text="Decision: ship it, see T-1")
    node(store, "Message", "m2", text="ok so we decided to wait")
    node(store, "Message", "m3", text="no decision here")
    t1 = node(store, "Ticket", "jira:issue:T-1")
    store.create_edge(G, bob.id, "AUTHORED", m1.id)
    store.create_edge(G, m1.id, "REFERENCES", t1.id)
    assert decisions(store, G) == {"SOURCED_FROM": 2, "DECIDED": 1, "AFFECTS": 1}
    assert links(store, "SOURCED_FROM") == {("decision:m1", "m1"), ("decision:m2", "m2")}
    assert links(store, "DECIDED") == {("bob", "decision:m1")}
    assert links(store, "AFFECTS") == {("decision:m1", "jira:issue:T-1")}


def test_knows_about_through_same_as(store):
    ada = node(store, "Person", "email:ada", name="Ada", email="ada@x.io")
    gh_ada = node(store, "Person", "gh:ada", name="Ada")
    kafka = node(store, "Topic", "topic:kafka", name="kafka")
    m1 = node(store, "Message", "m1")
    t1 = node(store, "Ticket", "t1")
    store.create_edge(G, gh_ada.id, "SAME_AS", ada.id)
    store.create_edge(G, ada.id, "AUTHORED", m1.id)
    store.create_edge(G, t1.id, "ASSIGNED_TO", gh_ada.id)
    for item in (m1, t1):
        store.create_edge(G, item.id, "ABOUT", kafka.id)
    assert knows_about(store, G) == {"KNOWS_ABOUT": 1}
    assert links(store, "KNOWS_ABOUT") == {("email:ada", "topic:kafka")}
    assert experts(store, G, "kafka") == [{"name": "Ada", "key": "email:ada", "score": 2}]
    assert experts(store, G, "nothing") == []
