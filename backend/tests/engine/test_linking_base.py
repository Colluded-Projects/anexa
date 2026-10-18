"""The shared ground every linking strategy is scored on."""

from anexa.graph import demo
from anexa.graph.evaluate import score
from anexa.graph.linking import STRATEGY, link_graph, write_link

G = "ws_demo"


def key_to_id(store):
    return {n.props["key"]: n.id for n in store.find_nodes(G)}


def test_demo_company_loads_with_split_identities(store):
    counts = demo.load(store, G)
    assert set(counts) == {"slack", "jira", "github", "google"}
    assert all(c["skipped"] == 0 for c in counts.values())
    by_label = store.count_by_label(G)
    # 4 real people, 9 Person nodes: e.g. Ada is an email, a GitHub login and a Jira id.
    assert by_label["Person"] == 9
    assert by_label["Message"] == 5 and by_label["Ticket"] == 5 and by_label["Document"] == 2
    texts = [n for n in store.find_nodes(G, "Message") if n.props.get("text")]
    assert len(texts) == 5


def test_unlinked_graph_scores_zero_recall(store):
    demo.load(store, G)
    result = score(store, G)
    assert set(result) == set(demo.GOLD)
    assert all(r["recall"] == 0 and r["found"] == 0 for r in result.values())


def test_perfect_links_score_one(store):
    demo.load(store, G)
    ids = key_to_id(store)
    for a, b in demo.GOLD["references"]:
        write_link(store, G, ids[a], "REFERENCES", ids[b], method="test", confidence=1.0)
    for name, type in {"same_person": "SAME_AS", "related": "RELATED_TO"}.items():
        for a, b in demo.GOLD[name]:
            # Unordered categories may be written in either direction.
            write_link(store, G, ids[b], type, ids[a], method="test", confidence=1.0)
    decision = store.create_node(G, "Decision", {"key": "d1", "name": "Kafka"})
    for (src,) in demo.GOLD["decisions"]:
        write_link(store, G, decision.id, "SOURCED_FROM", ids[src], method="test", confidence=1.0)

    result = score(store, G)
    for name in demo.GOLD:
        assert result[name] == {**result[name], "precision": 1.0, "recall": 1.0}


def test_wrong_links_lower_precision(store):
    demo.load(store, G)
    ids = key_to_id(store)
    write_link(store, G, ids[demo.M3], "RELATED_TO", ids[demo.API7], method="t", confidence=1)
    write_link(store, G, ids[demo.M3], "RELATED_TO", ids[demo.RFC1], method="t", confidence=1)
    related = score(store, G)["related"]
    assert related["correct"] == 1 and related["precision"] == 0.5 and related["recall"] == 0.2


def test_write_link_records_provenance(store):
    demo.load(store, G)
    ids = key_to_id(store)
    edge = write_link(
        store, G, ids[demo.M2], "REFERENCES", ids[demo.ENG12],
        method="regex", confidence=1.0, evidence="tracked in ENG-12",
    )
    assert edge.props == {
        "source": "linker", "method": "regex", "confidence": 1.0, "evidence": "tracked in ENG-12"
    }


def test_link_graph_returns_stats(store):
    demo.load(store, G)
    stats = link_graph(store, G)
    assert stats["strategy"] == STRATEGY
    assert isinstance(stats["links"], dict)
