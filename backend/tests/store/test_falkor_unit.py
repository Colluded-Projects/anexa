"""FalkorStore against a fake client: what Cypher it sends and how it reads
results. No server needed; behaviour on a real engine is covered by
test_contract.py."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from orgraph.store.base import GraphStore, NotFound, StoreError
from orgraph.store.falkor import (
    _NULL,
    _TAG,
    FalkorStore,
    decode_props,
    decode_value,
    encode_props,
    encode_value,
)


def result(rows=(), header=(), **stats) -> SimpleNamespace:
    return SimpleNamespace(
        result_set=[list(r) for r in rows],
        header=[[1, name] for name in header],
        nodes_deleted=stats.get("nodes_deleted", 0),
        relationships_deleted=stats.get("relationships_deleted", 0),
    )


class FakeGraph:
    def __init__(self, client: FakeClient, name: str) -> None:
        self.client, self.name = client, name

    def _call(self, kind: str, cypher: str, params: dict[str, Any] | None) -> Any:
        self.client.calls.append(
            SimpleNamespace(kind=kind, graph=self.name, q=cypher, params=params)
        )
        reply = self.client.replies.pop(0) if self.client.replies else result()
        if isinstance(reply, Exception):
            raise reply
        return reply

    def query(self, cypher, params=None):
        return self._call("query", cypher, params)

    def ro_query(self, cypher, params=None):
        return self._call("ro_query", cypher, params)

    def delete(self):
        self.client.deleted.append(self.name)


class FakeClient:
    """Records every query; replies are served in order (empty result by default)."""

    def __init__(self, graphs=("g",)) -> None:
        self.calls: list[SimpleNamespace] = []
        self.replies: list[Any] = []
        self.deleted: list[str] = []
        self.graphs = list(graphs)

    def select_graph(self, name: str) -> FakeGraph:
        return FakeGraph(self, name)

    def list_graphs(self) -> list[str]:
        return self.graphs


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def store(client) -> FalkorStore:
    return FalkorStore(client)


def node_row(label: str, **props) -> list[Any]:
    return [label, props]


# --- value encoding ----------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["text", "", 0, 7, -1, 1.5, True, False, ["a", "b"], [1, 2, 3], [1.5, 2.5], [True, False], []],
)
def test_native_values_are_stored_as_is(value):
    assert encode_value(value) == value
    assert type(encode_value(value)) is type(value)
    assert decode_value(encode_value(value)) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"a": 1, "b": [1, {"c": None}]},
        [[1, 2], [3]],
        [1, "a"],
        [1, True],  # bool and int are different types in FalkorDB
        [1, 2.5],
        ["a", None],
        [{"k": "v"}],
        _TAG + "looks encoded",
        [_TAG + "x"],
    ],
)
def test_non_native_values_become_tagged_json_and_round_trip(value):
    encoded = encode_value(value)
    assert isinstance(encoded, str) and encoded.startswith(_TAG)
    assert decode_value(encoded) == value


def test_tuples_are_stored_as_lists():
    assert encode_value(("a", "b")) == ["a", "b"]
    assert decode_value(encode_value((1, "a"))) == [1, "a"]


def test_encoding_is_deterministic_so_equality_filters_work():
    assert encode_value({"b": 1, "a": 2}) == encode_value({"a": 2, "b": 1})
    assert encode_value(None) == _NULL


def test_unserialisable_value_raises_store_error():
    with pytest.raises(StoreError):
        encode_value({"x": object()})


def test_props_round_trip():
    props = {"s": "x", "n": None, "d": {"a": [1, None]}, "tags": ["a"], "i": 3}
    encoded = encode_props(props)
    assert encoded["s"] == "x" and encoded["tags"] == ["a"] and encoded["i"] == 3
    assert all(isinstance(encoded[k], str) for k in ("n", "d"))
    assert decode_props(encoded) == props
    assert decode_props(None) == {}


# --- identifier validation ---------------------------------------------------

BAD_NAMES = [
    "",
    "Person) DETACH DELETE (m",
    "a b",
    "a-b",
    "a.b",
    "a`b",
    "1abc",
    "x:Admin",
    "x}) RETURN 1 //",
    "naïve",
    None,
    7,
]


@pytest.mark.parametrize("bad", BAD_NAMES)
def test_bad_labels_types_and_property_names_never_reach_the_server(store, client, bad):
    attempts = [
        lambda: store.create_node("g", bad, {"a": 1}),
        lambda: store.create_node("g", "Person", {bad: 1}),
        lambda: store.find_nodes("g", bad) if bad else (_ for _ in ()).throw(StoreError("skip")),
        lambda: store.find_nodes("g", "Person", {bad: 1}),
        lambda: store.find_nodes("g", "Person", contains={bad: "x"}),
        lambda: (
            store.find_nodes("g", "Person", order_by=bad)
            if bad
            else (_ for _ in ()).throw(StoreError("skip"))
        ),
        lambda: store.update_node("g", "id", {bad: 1}),
        lambda: store.upsert_node("g", bad, {"key": "k"}, {}),
        lambda: store.upsert_node("g", "Person", {bad: "k"}, {}),
        lambda: store.upsert_node("g", "Person", {"key": "k"}, {bad: 1}),
        lambda: store.create_edge("g", "a", bad, "b"),
        lambda: store.create_edge("g", "a", "T", "b", {bad: 1}),
        lambda: store.delete_edge("g", "a", bad, "b"),
    ]
    for attempt in attempts:
        with pytest.raises(StoreError):
            attempt()
    assert client.calls == []


def test_values_are_always_parameters_never_query_text(store, client):
    evil = "x'}) DETACH DELETE (n) //"
    client.replies = [result(), result(), result([node_row("Person", id=evil, name=evil)])]
    store.create_node("g", "Person", {"id": evil, "name": evil})
    store.find_nodes("g", "Person", {"name": evil}, contains={"name": evil})
    store.get_node("g", evil)
    store.edges("g", evil)
    assert client.calls
    assert all(evil not in call.q and evil.lower() not in call.q for call in client.calls)


# --- nodes -------------------------------------------------------------------


def test_implements_protocol(store):
    assert isinstance(store, GraphStore)


def test_create_node_checks_id_then_indexes_then_creates(store, client):
    client.replies = [result(), result(), result([node_row("Person", id="p1", name="Ada")])]
    node = store.create_node("g", "Person", {"id": "p1", "name": "Ada", "meta": {"a": 1}})
    exists, index, create = client.calls
    assert exists.kind == "ro_query" and exists.params == {"id": "p1"}
    assert index.q == "CREATE INDEX FOR (n:Person) ON (n.id)"
    assert create.kind == "query" and create.q.startswith("CREATE (n:Person) SET n = $props")
    assert create.params["props"] == {"id": "p1", "name": "Ada", "meta": encode_value({"a": 1})}
    assert (node.id, node.label, node.props) == ("p1", "Person", {"id": "p1", "name": "Ada"})


def test_create_node_generates_id(store, client):
    client.replies = [result(), result(), result([node_row("Person", id="ignored")])]
    store.create_node("g", "Person", {"name": "Ada"})
    sent = client.calls[-1].params["props"]
    assert isinstance(sent["id"], str) and len(sent["id"]) == 32
    assert client.calls[0].params == {"id": sent["id"]}


def test_create_node_duplicate_id_raises_without_writing(store, client):
    client.replies = [result([["p1"]])]
    with pytest.raises(StoreError):
        store.create_node("g", "Person", {"id": "p1"})
    assert [c.kind for c in client.calls] == ["ro_query"]


def test_index_is_created_once_per_graph_and_label_and_failures_are_ignored(store, client):
    def create(graph, label, index_reply):
        client.replies = [result(), *index_reply, result([node_row(label, id="x")])]
        store.create_node(graph, label, {})

    create("g", "Person", [RuntimeError("Attribute 'id' is already indexed")])
    create("g", "Person", [])
    create("g", "Team", [result()])
    create("h", "Person", [result()])
    indexes = [(c.graph, c.q) for c in client.calls if c.q.startswith("CREATE INDEX")]
    assert indexes == [
        ("g", "CREATE INDEX FOR (n:Person) ON (n.id)"),
        ("g", "CREATE INDEX FOR (n:Team) ON (n.id)"),
        ("h", "CREATE INDEX FOR (n:Person) ON (n.id)"),
    ]


def test_get_node_decodes_props(store, client):
    client.replies = [
        result([node_row("Person", id="p1", meta=encode_value({"a": None}), n=_NULL)])
    ]
    node = store.get_node("g", "p1", "Person")
    assert node.props == {"id": "p1", "meta": {"a": None}, "n": None}
    call = client.calls[0]
    assert call.kind == "ro_query"
    assert call.q.startswith("MATCH (n:Person {id: $id})") and call.params == {"id": "p1"}

    client.replies = [result()]
    assert store.get_node("g", "nope") is None
    assert client.calls[-1].q.startswith("MATCH (n {id: $id})")


def test_find_nodes_plain(store, client):
    client.replies = [result([node_row("A", id="1"), node_row("B", id="2")])]
    found = store.find_nodes("g")
    assert [(n.id, n.label) for n in found] == [("1", "A"), ("2", "B")]
    call = client.calls[0]
    assert call.kind == "ro_query"
    assert call.q == "MATCH (n) RETURN labels(n)[0], properties(n) ORDER BY ID(n) ASC"
    assert call.params == {}


def test_find_nodes_where_clause(store, client):
    store.find_nodes("g", "Person", {"team": "eng", "age": 3, "meta": {"a": 1}, "gone": None})
    call = client.calls[0]
    assert call.q.startswith("MATCH (n:Person) WHERE ")
    assert (
        "n.team = $w0 AND n.age = $w1 AND n.meta = $w2 AND (n.gone IS NULL OR n.gone = $w3)"
        in call.q
    )
    assert call.params == {"w0": "eng", "w1": 3, "w2": encode_value({"a": 1}), "w3": _NULL}


def test_find_nodes_contains_clause_is_lowercased_and_type_guarded(store, client):
    store.find_nodes("g", "Person", {"team": "eng"}, contains={"name": "ADA"})
    call = client.calls[0]
    assert call.params == {"w0": "eng", "c0": "ada", "tag": _TAG}
    text = "(CASE WHEN typeOf(n.name) = 'String' THEN n.name ELSE $tag END)"
    assert f"n.team = $w0 AND (NOT {text} STARTS WITH $tag" in call.q
    assert f"toLower({text}) CONTAINS $c0" in call.q


def test_find_nodes_order_skip_limit(store, client):
    store.find_nodes("g", "Person", order_by="age", desc=True, skip=5, limit=10)
    call = client.calls[0]
    assert call.q.endswith(
        "ORDER BY (n.age IS NULL OR n.age = $null) ASC, n.age DESC, ID(n) ASC"
        " SKIP $skip LIMIT $limit"
    )
    assert call.params == {"null": _NULL, "skip": 5, "limit": 10}

    store.find_nodes("g", "Person", order_by="age", limit=0)
    call = client.calls[-1]
    assert "n.age ASC, ID(n) ASC LIMIT $limit" in call.q and "SKIP" not in call.q
    assert call.params == {"null": _NULL, "limit": 0}


def test_update_node(store, client):
    client.replies = [result([node_row("Person", id="p1", name="Bob", gone=_NULL)])]
    node = store.update_node("g", "p1", {"id": "other", "name": "Bob", "gone": None})
    call = client.calls[0]
    assert call.kind == "query"
    assert call.q.startswith("MATCH (n {id: $id}) SET n += $props")
    assert call.params == {"id": "p1", "props": {"name": "Bob", "gone": _NULL}}
    assert node.props == {"id": "p1", "name": "Bob", "gone": None}


def test_update_node_missing_raises_not_found(store, client):
    with pytest.raises(NotFound):
        store.update_node("g", "nope", {"a": 1})
    with pytest.raises(NotFound):
        store.update_node("g", "nope", {})


def test_delete_node(store, client):
    client.replies = [result([node_row("Person", id="p1")]), result(nodes_deleted=1)]
    assert store.delete_node("g", "p1") is True
    assert client.calls[-1].q == "MATCH (n {id: $id}) DELETE n"
    assert client.calls[-1].params == {"id": "p1"}

    client.calls.clear()
    assert store.delete_node("g", "nope") is False
    assert [c.kind for c in client.calls] == ["ro_query"]


def test_upsert_node_merges_on_key(store, client):
    client.replies = [result(), result([node_row("Person", id="p1", key="k", name="Ada")])]
    node = store.upsert_node("g", "Person", {"key": "k", "n": 1}, {"name": "Ada", "id": "p1"})
    call = client.calls[-1]
    assert call.q.startswith(
        "MERGE (n:Person {key: $k0, n: $k1}) ON CREATE SET n.id = $new_id SET n += $props"
    )
    assert call.params == {"k0": "k", "k1": 1, "new_id": "p1", "props": {"name": "Ada"}}
    assert node.id == "p1"


def test_upsert_node_rejects_empty_or_non_scalar_key(store, client):
    for key in ({}, {"key": None}, {"key": {"a": 1}}, {"key": [1, "a"]}):
        with pytest.raises(StoreError):
            store.upsert_node("g", "Person", key, {})
    assert client.calls == []


# --- edges -------------------------------------------------------------------


def test_create_edge(store, client):
    client.replies = [
        result([node_row("A", id="a")]),
        result([node_row("B", id="b")]),
        result([[{"role": "owner", "meta": encode_value({"x": 1})}]]),
    ]
    edge = store.create_edge("g", "a", "MEMBER_OF", "b", {"role": "owner", "meta": {"x": 1}})
    call = client.calls[-1]
    assert call.kind == "query"
    assert "MERGE (a)-[r:MEMBER_OF]->(b) SET r += $props" in call.q
    assert call.params == {
        "src": "a",
        "dst": "b",
        "props": {"role": "owner", "meta": encode_value({"x": 1})},
    }
    assert (edge.src, edge.type, edge.dst) == ("a", "MEMBER_OF", "b")
    assert edge.props == {"role": "owner", "meta": {"x": 1}}


def test_create_edge_missing_endpoint_does_not_write(store, client):
    client.replies = [result([node_row("A", id="a")]), result()]
    with pytest.raises(NotFound):
        store.create_edge("g", "a", "MEMBER_OF", "nope")
    assert all(c.kind == "ro_query" for c in client.calls)


def test_delete_edge(store, client):
    client.replies = [result([["a"]]), result(relationships_deleted=1)]
    assert store.delete_edge("g", "a", "MEMBER_OF", "b") is True
    assert client.calls[-1].q == "MATCH (a {id: $src})-[r:MEMBER_OF]->(b {id: $dst}) DELETE r"
    assert client.calls[-1].params == {"src": "a", "dst": "b"}

    client.calls.clear()
    assert store.delete_edge("g", "a", "MEMBER_OF", "b") is False
    assert [c.kind for c in client.calls] == ["ro_query"]


def test_edges_queries_per_direction(store, client):
    store.edges("g")
    assert client.calls[-1].q.startswith("MATCH (a)-[r]->(b) RETURN a.id, type(r), b.id")
    store.edges("g", type="OWNS", limit=3)
    assert client.calls[-1].q.startswith("MATCH (a)-[r:OWNS]->(b)")
    assert client.calls[-1].q.endswith("LIMIT $limit") and client.calls[-1].params == {"limit": 3}

    client.calls.clear()
    store.edges("g", "x", direction="out")
    assert [c.q.split(" RETURN")[0] for c in client.calls] == ["MATCH (a {id: $id})-[r]->(b)"]
    client.calls.clear()
    store.edges("g", "x", direction="in")
    assert [c.q.split(" RETURN")[0] for c in client.calls] == ["MATCH (a)-[r]->(b {id: $id})"]
    client.calls.clear()
    store.edges("g", "x", "OWNS")
    assert [c.q.split(" RETURN")[0] for c in client.calls] == [
        "MATCH (a {id: $id})-[r:OWNS]->(b)",
        "MATCH (a)-[r:OWNS]->(b {id: $id})",
    ]
    assert all(c.kind == "ro_query" and c.params == {"id": "x"} for c in client.calls)


def test_edges_both_dedups_self_loops_and_applies_limit(store, client):
    out_rows = [["x", "REFERENCES", "x", {}], ["x", "OWNS", "y", {"w": _NULL}]]
    in_rows = [["x", "REFERENCES", "x", {}], ["z", "OWNS", "x", {}]]
    client.replies = [result(out_rows), result(in_rows)]
    edges = store.edges("g", "x")
    assert [(e.src, e.type, e.dst) for e in edges] == [
        ("x", "REFERENCES", "x"),
        ("x", "OWNS", "y"),
        ("z", "OWNS", "x"),
    ]
    assert edges[1].props == {"w": None}

    client.replies = [result(out_rows), result(in_rows)]
    assert len(store.edges("g", "x", limit=2)) == 2


def test_neighbors_fetches_other_ends_in_edge_order(store, client):
    client.replies = [
        result([["x", "OWNS", "b", {}], ["x", "OWNS", "a", {}]]),
        result([["a", "REFERENCES", "x", {}]]),
        result([node_row("T", id="a"), node_row("T", id="b")]),
    ]
    found = store.neighbors("g", "x", label="T")
    assert [n.id for n in found] == ["b", "a"]
    call = client.calls[-1]
    assert call.q.startswith("MATCH (n:T) WHERE n.id IN $ids") and call.params == {
        "ids": ["b", "a"]
    }


def test_neighbors_without_edges_skips_the_node_query(store, client):
    assert store.neighbors("g", "x") == []
    assert len(client.calls) == 2


def test_count_by_label(store, client):
    client.replies = [result([["Person", 4], ["Team", 1]])]
    assert store.count_by_label("g") == {"Person": 4, "Team": 1}
    assert client.calls[0].kind == "ro_query"


# --- raw query ---------------------------------------------------------------


def test_query_is_read_only_by_default(store, client):
    client.replies = [result([[1, "a"]], header=["n", "s"])]
    assert store.query("g", "RETURN 1 AS n, 'a' AS s", {"p": 1}) == [{"n": 1, "s": "a"}]
    call = client.calls[0]
    assert (call.kind, call.q, call.params) == ("ro_query", "RETURN 1 AS n, 'a' AS s", {"p": 1})

    store.query("g", "CREATE (n)", readonly=False)
    assert client.calls[-1].kind == "query"


def test_query_converts_nodes_edges_paths_and_nested_values(store, client):
    node = SimpleNamespace(id=3, labels=["Person"], properties={"id": "p1", "meta": _NULL})
    edge = SimpleNamespace(id=9, relation="OWNS", src_node=3, dest_node=4, properties={"w": 1})
    path = SimpleNamespace(nodes=lambda: [node], edges=lambda: [edge])
    client.replies = [
        result(
            [[node, edge, path, [node, 1], {"k": edge}, encode_value({"a": 1}), b"raw"]],
            header=[b"n", "r", "p", "list", "map", "enc", "bytes"],
        )
    ]
    row = store.query("g", "MATCH ...")[0]
    plain_node = {
        "id": "p1",
        "label": "Person",
        "labels": ["Person"],
        "props": {"id": "p1", "meta": None},
    }
    plain_edge = {"type": "OWNS", "props": {"w": 1}}
    assert row == {
        "n": plain_node,
        "r": plain_edge,
        "p": {"nodes": [plain_node], "edges": [plain_edge]},
        "list": [plain_node, 1],
        "map": {"k": plain_edge},
        "enc": {"a": 1},
        "bytes": "raw",
    }


def test_query_errors_become_store_errors(store, client):
    client.replies = [RuntimeError("Invalid input 'X'")]
    with pytest.raises(StoreError, match="Invalid input"):
        store.query("g", "X")
    client.replies = [RuntimeError("graph.RO_QUERY is to be executed only on read-only queries")]
    with pytest.raises(StoreError):
        store.query("g", "CREATE (n)")


# --- missing graphs ----------------------------------------------------------


def test_reads_on_a_missing_graph_are_empty(client):
    client.graphs = []
    store = FalkorStore(client)
    client.replies = [RuntimeError("Invalid graph operation on empty key")] * 20
    assert store.get_node("nope", "x") is None
    assert store.find_nodes("nope") == []
    assert store.edges("nope") == []
    assert store.neighbors("nope", "x") == []
    assert store.count_by_label("nope") == {}
    assert store.query("nope", "MATCH (n) RETURN n") == []
    assert store.delete_node("nope", "x") is False
    assert store.delete_edge("nope", "a", "T", "b") is False
    assert all(c.kind == "ro_query" for c in client.calls)  # nothing created the graph


def test_read_error_on_an_existing_graph_is_raised(store, client):
    client.replies = [RuntimeError("connection reset")]
    with pytest.raises(StoreError, match="connection reset"):
        store.find_nodes("g")


def test_delete_graph(store, client):
    store.delete_graph("g")
    assert client.deleted == ["g"]
    store.delete_graph("missing")
    assert client.deleted == ["g"]


def test_delete_graph_forgets_its_indexes(store, client):
    client.replies = [result(), result(), result([node_row("P", id="1")])]
    store.create_node("g", "P", {})
    store.delete_graph("g")
    client.calls.clear()
    client.replies = [result(), result(), result([node_row("P", id="2")])]
    store.create_node("g", "P", {})
    assert any(c.q.startswith("CREATE INDEX") for c in client.calls)


def test_from_settings_builds_a_client(monkeypatch):
    import falkordb

    seen = {}
    monkeypatch.setattr(falkordb, "FalkorDB", lambda **kw: seen.update(kw) or "client")
    settings = SimpleNamespace(
        falkordb_host="db", falkordb_port=6390, falkordb_username="u", falkordb_password="p"
    )
    store = FalkorStore.from_settings(settings)
    assert store._client == "client"
    assert seen == {"host": "db", "port": 6390, "username": "u", "password": "p"}
