from orgraph.connectors import EdgeUpsert, GraphDelta, NodeUpsert
from orgraph.graph.ingest import apply_delta

G = "company_test"


def person(key, **props):
    return NodeUpsert(label="Person", key=key, props=props)


def edge(src, type, dst, src_label="Person", dst_label="Team", **props):
    return EdgeUpsert(
        src_label=src_label, src_key=src, type=type, dst_label=dst_label, dst_key=dst, props=props
    )


def test_creates_nodes_and_edges(store):
    delta = GraphDelta(
        nodes=[
            person("email:a@x.io", name="Ada", url="https://x.io/ada"),
            NodeUpsert(label="Team", key="slack:channel:C1", props={"name": "eng"}),
        ],
        edges=[edge("email:a@x.io", "MEMBER_OF", "slack:channel:C1", role="lead")],
    )

    counts = apply_delta(store, G, delta, "slack")

    assert counts == {"nodes": 2, "edges": 1, "skipped": 0}
    [ada] = store.find_nodes(G, "Person")
    assert ada.props["key"] == "email:a@x.io"
    assert ada.props["name"] == "Ada" and ada.props["source"] == "slack"
    assert ada.props["url"] == "https://x.io/ada" and ada.props["updated_at"]
    [link] = store.edges(G, ada.id, direction="out")
    assert link.type == "MEMBER_OF" and link.props == {"role": "lead", "source": "slack"}


def test_reapplying_is_idempotent(store):
    delta = GraphDelta(
        nodes=[person("email:a@x.io", name="Ada"), NodeUpsert(label="Team", key="t", props={})],
        edges=[edge("email:a@x.io", "MEMBER_OF", "t")],
    )
    apply_delta(store, G, delta, "slack")
    apply_delta(store, G, delta, "slack")
    assert store.count_by_label(G) == {"Person": 1, "Team": 1}
    assert len(store.edges(G)) == 1


def test_same_key_merges_across_sources(store):
    apply_delta(
        store, G, GraphDelta(nodes=[person("email:a@x.io", name="Ada", slack_id="U1")]), "slack"
    )
    apply_delta(store, G, GraphDelta(nodes=[person("email:a@x.io", github_login="ada")]), "github")
    [ada] = store.find_nodes(G, "Person")
    assert ada.props["slack_id"] == "U1" and ada.props["github_login"] == "ada"
    assert ada.props["name"] == "Ada"
    assert ada.props["source"] == "github"


def test_same_key_under_different_labels_are_distinct(store):
    delta = GraphDelta(
        nodes=[NodeUpsert(label="Team", key="k"), NodeUpsert(label="Project", key="k")]
    )
    assert apply_delta(store, G, delta, "x")["nodes"] == 2
    assert store.count_by_label(G) == {"Team": 1, "Project": 1}


def test_name_defaults_to_key_and_none_props_are_dropped(store):
    apply_delta(store, G, GraphDelta(nodes=[person("github:user:1", url=None)]), "github")
    [node] = store.find_nodes(G, "Person")
    assert node.props["name"] == "github:user:1"
    assert "url" not in node.props


def test_none_prop_does_not_erase_existing_value(store):
    apply_delta(store, G, GraphDelta(nodes=[person("k", url="https://a")]), "a")
    apply_delta(store, G, GraphDelta(nodes=[person("k", url=None)]), "b")
    assert store.find_nodes(G, "Person")[0].props["url"] == "https://a"


def test_edge_to_node_already_in_graph(store):
    apply_delta(store, G, GraphDelta(nodes=[NodeUpsert(label="Team", key="t")]), "a")
    delta = GraphDelta(nodes=[person("p")], edges=[edge("p", "MEMBER_OF", "t")])
    assert apply_delta(store, G, delta, "b") == {"nodes": 1, "edges": 1, "skipped": 0}


def test_unknown_label_type_and_dangling_edges_are_skipped(store):
    delta = GraphDelta(
        nodes=[person("p"), NodeUpsert(label="Alien", key="z")],
        edges=[
            edge("p", "MEMBER_OF", "missing"),
            edge("p", "ABDUCTED_BY", "p", dst_label="Person"),
            edge("p", "REFERENCES", "z", dst_label="Alien"),
        ],
    )
    assert apply_delta(store, G, delta, "x") == {"nodes": 1, "edges": 0, "skipped": 4}
    assert store.count_by_label(G) == {"Person": 1}
    assert store.edges(G) == []


def test_empty_delta(store):
    assert apply_delta(store, G, GraphDelta(), "x") == {"nodes": 0, "edges": 0, "skipped": 0}
