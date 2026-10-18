"""Contract every GraphStore implementation must satisfy (see store/base.py).

The memory backend always runs. The falkor backend runs when a real FalkorDB
is reachable, selected by environment:

  ANEXA_TEST_FALKOR_HOST / ANEXA_TEST_FALKOR_PORT   server (default localhost:6379)
  ANEXA_TEST_FALKOR_LITE=1                            embedded falkordblite instead

A plain Redis/Valkey without the graph module counts as unreachable.
"""

from __future__ import annotations

import os
import uuid

import pytest

from anexa.store.base import GraphStore, NotFound, StoreError
from anexa.store.memory import MemoryStore


def _falkor_client():
    """Return a client for a real FalkorDB engine, or None when there is none."""
    try:
        if os.environ.get("ANEXA_TEST_FALKOR_LITE"):
            import tempfile

            from redislite.falkordb_client import FalkorDB as LiteDB

            client = LiteDB(os.path.join(tempfile.mkdtemp(prefix="anexa-falkor-"), "test.db"))
        else:
            from falkordb import FalkorDB

            client = FalkorDB(
                host=os.environ.get("ANEXA_TEST_FALKOR_HOST", "localhost"),
                port=int(os.environ.get("ANEXA_TEST_FALKOR_PORT", "6379")),
                socket_connect_timeout=1,
            )
        probe = client.select_graph(f"anexa_probe_{uuid.uuid4().hex}")
        probe.query("RETURN 1")  # fails on a server without the graph module
        try:
            probe.delete()
        except Exception:
            pass
        return client
    except Exception:
        return None


@pytest.fixture(scope="session")
def falkor_client():
    return _falkor_client()


@pytest.fixture(params=["memory", pytest.param("falkor", marks=pytest.mark.falkor)])
def store(request) -> GraphStore:
    if request.param == "memory":
        return MemoryStore()
    client = request.getfixturevalue("falkor_client")
    if client is None:
        pytest.skip("no reachable FalkorDB")
    from anexa.store.falkor import FalkorStore

    return FalkorStore(client)


@pytest.fixture
def new_graph(store):
    """Factory for uniquely named graphs, deleted after the test."""
    names: list[str] = []

    def make() -> str:
        names.append(f"anexa_test_{uuid.uuid4().hex}")
        return names[-1]

    yield make
    for name in names:
        store.delete_graph(name)


@pytest.fixture
def g(new_graph) -> str:
    return new_graph()


def ids(nodes) -> list[str]:
    return [n.id for n in nodes]


# --- protocol ----------------------------------------------------------------


def test_implements_protocol(store):
    assert isinstance(store, GraphStore)


# --- create / get ------------------------------------------------------------


def test_create_generates_id_and_stores_it_in_props(store, g):
    node = store.create_node(g, "Person", {"name": "Ada"})
    assert isinstance(node.id, str) and node.id
    assert node.label == "Person"
    assert node.props == {"name": "Ada", "id": node.id}
    other = store.create_node(g, "Person", {"name": "Bob"})
    assert other.id != node.id


def test_create_uses_supplied_id(store, g):
    node = store.create_node(g, "Person", {"id": "p1", "name": "Ada"})
    assert node.id == "p1"
    assert store.get_node(g, "p1").props == {"id": "p1", "name": "Ada"}


def test_create_duplicate_id_raises_even_across_labels(store, g):
    store.create_node(g, "Person", {"id": "x"})
    with pytest.raises(StoreError):
        store.create_node(g, "Person", {"id": "x"})
    with pytest.raises(StoreError):
        store.create_node(g, "Team", {"id": "x"})
    assert len(store.find_nodes(g)) == 1


def test_create_does_not_alias_caller_props(store, g):
    props = {"name": "Ada", "meta": {"a": [1]}}
    node = store.create_node(g, "Person", props)
    props["meta"]["a"].append(2)
    assert "id" not in props
    assert store.get_node(g, node.id).props["meta"] == {"a": [1]}


def test_get_node_label_filter_and_missing(store, g):
    store.create_node(g, "Person", {"id": "p1"})
    assert store.get_node(g, "p1").label == "Person"
    assert store.get_node(g, "p1", "Person").id == "p1"
    assert store.get_node(g, "p1", "Team") is None
    assert store.get_node(g, "nope") is None


# --- property round trips ----------------------------------------------------


def test_property_values_round_trip(store, g):
    props = {
        "s": "text",
        "empty_s": "",
        "unicode": "naïve — 'quoted' \"double\" \\ back\nline",
        "i": 7,
        "neg": -3,
        "f": 1.5,
        "t": True,
        "fa": False,
        "none": None,
        "tags": ["a", "b"],
        "nums": [1, 2, 3],
        "floats": [1.5, 2.5],
        "empty_list": [],
        "mixed": [1, "a", None],
        "nested": [[1, 2], [3]],
        "d": {"a": 1, "b": [1, {"c": None}], "e": {"f": "g"}},
        "empty_d": {},
        "dicts": [{"key": "k", "n": 1}, {"key": "j", "n": 2}],
    }
    node = store.create_node(g, "Thing", props)
    got = store.get_node(g, node.id).props
    assert got == {**props, "id": node.id}
    assert got["t"] is True and got["fa"] is False
    assert isinstance(got["i"], int) and not isinstance(got["i"], bool)
    assert "none" in got and got["none"] is None
    # the same values come back from every read path
    assert store.find_nodes(g, "Thing")[0].props == got
    assert node.props == got


def test_scalar_and_scalar_list_props_are_filterable(store, g):
    store.create_node(g, "T", {"id": "a", "n": 1, "ok": True, "tags": ["x", "y"], "s": "p"})
    store.create_node(g, "T", {"id": "b", "n": 2, "ok": False, "tags": ["x"], "s": "q"})
    assert ids(store.find_nodes(g, "T", {"n": 2})) == ["b"]
    assert ids(store.find_nodes(g, "T", {"ok": True})) == ["a"]
    assert ids(store.find_nodes(g, "T", {"s": "q"})) == ["b"]
    assert ids(store.find_nodes(g, "T", {"tags": ["x", "y"]})) == ["a"]


# --- find --------------------------------------------------------------------


@pytest.fixture
def people(store, g):
    rows = [
        ("p1", "Person", {"name": "Ada Lovelace", "team": "eng", "age": 36}),
        ("p2", "Person", {"name": "Grace Hopper", "team": "eng", "age": 85}),
        ("p3", "Person", {"name": "Alan Turing", "team": "research", "age": 41}),
        ("p4", "Person", {"name": "ada byron", "team": "research"}),
        ("t1", "Team", {"name": "Engineering", "team": "eng"}),
    ]
    for node_id, label, props in rows:
        store.create_node(g, label, {"id": node_id, **props})
    return g


def test_find_all_and_by_label(store, people):
    assert sorted(ids(store.find_nodes(people))) == ["p1", "p2", "p3", "p4", "t1"]
    assert sorted(ids(store.find_nodes(people, "Person"))) == ["p1", "p2", "p3", "p4"]
    assert ids(store.find_nodes(people, "Team")) == ["t1"]
    assert store.find_nodes(people, "Nothing") == []


def test_find_where_requires_all_to_match(store, people):
    assert sorted(ids(store.find_nodes(people, "Person", {"team": "eng"}))) == ["p1", "p2"]
    assert ids(store.find_nodes(people, "Person", {"team": "eng", "age": 85})) == ["p2"]
    assert store.find_nodes(people, "Person", {"team": "eng", "age": 1}) == []
    assert sorted(ids(store.find_nodes(people, None, {"team": "eng"}))) == ["p1", "p2", "t1"]


def test_find_contains_is_case_insensitive_and_all_must_match(store, people):
    assert sorted(ids(store.find_nodes(people, "Person", contains={"name": "ADA"}))) == ["p1", "p4"]
    assert ids(store.find_nodes(people, "Person", contains={"name": "ada", "team": "RESE"})) == [
        "p4"
    ]
    assert ids(store.find_nodes(people, "Person", {"team": "eng"}, contains={"name": "ada"})) == [
        "p1"
    ]
    assert store.find_nodes(people, "Person", contains={"name": "zzz"}) == []


def test_find_contains_ignores_missing_and_non_string_props(store, g):
    store.create_node(g, "T", {"id": "a", "v": "x12y"})
    store.create_node(g, "T", {"id": "b", "v": 12})
    store.create_node(g, "T", {"id": "c", "v": {"k": "12"}})
    store.create_node(g, "T", {"id": "d", "v": ["12"]})
    store.create_node(g, "T", {"id": "e", "v": None})
    store.create_node(g, "T", {"id": "f"})
    assert ids(store.find_nodes(g, "T", contains={"v": "12"})) == ["a"]


def test_find_order_by_asc_desc_and_missing_sorts_last(store, people):
    asc = ids(store.find_nodes(people, "Person", order_by="age"))
    assert asc == ["p1", "p3", "p2", "p4"]
    desc = ids(store.find_nodes(people, "Person", order_by="age", desc=True))
    assert desc == ["p2", "p3", "p1", "p4"]
    by_name = ids(store.find_nodes(people, "Person", order_by="name"))
    assert by_name == ["p1", "p3", "p2", "p4"]  # uppercase sorts before lowercase


def test_find_order_by_treats_stored_none_as_missing(store, g):
    store.create_node(g, "T", {"id": "a", "n": None})
    store.create_node(g, "T", {"id": "b", "n": 2})
    store.create_node(g, "T", {"id": "c", "n": 1})
    assert ids(store.find_nodes(g, "T", order_by="n")) == ["c", "b", "a"]
    assert ids(store.find_nodes(g, "T", order_by="n", desc=True)) == ["b", "c", "a"]


def test_find_skip_and_limit(store, people):
    ordered = ["p1", "p3", "p2", "p4"]
    find = lambda **kw: ids(store.find_nodes(people, "Person", order_by="age", **kw))  # noqa: E731
    assert find(limit=2) == ordered[:2]
    assert find(skip=1) == ordered[1:]
    assert find(skip=1, limit=2) == ordered[1:3]
    assert find(skip=10) == []
    assert find(limit=0) == []
    assert find(skip=3, limit=5) == ordered[3:]


def test_find_returns_copies(store, g):
    store.create_node(g, "T", {"id": "a", "meta": {"k": 1}})
    found = store.find_nodes(g, "T")[0]
    found.props["meta"]["k"] = 2
    found.props["extra"] = True
    assert store.get_node(g, "a").props == {"id": "a", "meta": {"k": 1}}


# --- update ------------------------------------------------------------------


def test_update_merges_props(store, g):
    store.create_node(g, "Person", {"id": "p1", "name": "Ada", "age": 36})
    updated = store.update_node(g, "p1", {"age": 37, "team": "eng", "meta": {"a": 1}})
    expected = {"id": "p1", "name": "Ada", "age": 37, "team": "eng", "meta": {"a": 1}}
    assert updated.props == expected
    assert updated.label == "Person"
    assert store.get_node(g, "p1").props == expected


def test_update_none_is_stored_as_none(store, g):
    store.create_node(g, "Person", {"id": "p1", "name": "Ada"})
    store.update_node(g, "p1", {"name": None})
    props = store.get_node(g, "p1").props
    assert "name" in props and props["name"] is None


def test_update_cannot_change_id(store, g):
    store.create_node(g, "Person", {"id": "p1", "name": "Ada"})
    updated = store.update_node(g, "p1", {"id": "p2", "name": "Bob"})
    assert updated.id == "p1" and updated.props["id"] == "p1"
    assert store.get_node(g, "p2") is None
    assert store.get_node(g, "p1").props == {"id": "p1", "name": "Bob"}


def test_update_with_nothing_to_change_returns_node(store, g):
    store.create_node(g, "Person", {"id": "p1", "name": "Ada"})
    assert store.update_node(g, "p1", {}).props == {"id": "p1", "name": "Ada"}


def test_update_missing_raises_not_found(store, g):
    with pytest.raises(NotFound):
        store.update_node(g, "nope", {"a": 1})


# --- delete ------------------------------------------------------------------


def test_delete_node_removes_it_and_its_edges(store, g):
    for node_id in ("a", "b", "c"):
        store.create_node(g, "T", {"id": node_id})
    store.create_edge(g, "a", "LINKS", "b")
    store.create_edge(g, "b", "LINKS", "c")
    store.create_edge(g, "a", "LINKS", "c")
    assert store.delete_node(g, "b") is True
    assert store.get_node(g, "b") is None
    remaining = store.edges(g)
    assert [(e.src, e.type, e.dst) for e in remaining] == [("a", "LINKS", "c")]
    assert ids(store.neighbors(g, "a")) == ["c"]


def test_delete_missing_node_returns_false(store, g):
    assert store.delete_node(g, "nope") is False
    store.create_node(g, "T", {"id": "a"})
    assert store.delete_node(g, "a") is True
    assert store.delete_node(g, "a") is False


# --- upsert ------------------------------------------------------------------


def test_upsert_creates_with_key_and_props(store, g):
    node = store.upsert_node(g, "Person", {"key": "email:a@x.io"}, {"name": "Ada"})
    assert node.label == "Person"
    assert node.props == {"id": node.id, "key": "email:a@x.io", "name": "Ada"}
    assert store.get_node(g, node.id, "Person").props == node.props


def test_upsert_merges_into_existing(store, g):
    first = store.upsert_node(g, "Person", {"key": "k1"}, {"name": "Ada", "age": 1})
    second = store.upsert_node(g, "Person", {"key": "k1"}, {"age": 2, "meta": {"a": None}})
    assert second.id == first.id
    assert second.props == {
        "id": first.id,
        "key": "k1",
        "name": "Ada",
        "age": 2,
        "meta": {"a": None},
    }
    assert len(store.find_nodes(g, "Person")) == 1


def test_upsert_matches_label_and_every_key_part(store, g):
    a = store.upsert_node(g, "Person", {"key": "k1"}, {"name": "person"})
    b = store.upsert_node(g, "Team", {"key": "k1"}, {"name": "team"})
    assert a.id != b.id
    c = store.upsert_node(g, "Doc", {"source": "google", "ext": 1}, {"name": "one"})
    d = store.upsert_node(g, "Doc", {"source": "google", "ext": 2}, {"name": "two"})
    e = store.upsert_node(g, "Doc", {"source": "google", "ext": 1}, {"name": "uno"})
    assert c.id != d.id and e.id == c.id
    assert store.get_node(g, c.id).props["name"] == "uno"
    assert store.count_by_label(g) == {"Person": 1, "Team": 1, "Doc": 2}


def test_upsert_keeps_id_of_existing_node(store, g):
    store.create_node(g, "Person", {"id": "p1", "key": "k1"})
    node = store.upsert_node(g, "Person", {"key": "k1"}, {"id": "other", "name": "Ada"})
    assert node.id == "p1"
    assert store.get_node(g, "other") is None


# --- edges -------------------------------------------------------------------


@pytest.fixture
def abc(store, g):
    for node_id, label in (("a", "Person"), ("b", "Team"), ("c", "Project")):
        store.create_node(g, label, {"id": node_id})
    return g


def test_create_edge_returns_edge(store, abc):
    edge = store.create_edge(abc, "a", "MEMBER_OF", "b", {"role": "owner"})
    assert (edge.src, edge.type, edge.dst, edge.props) == ("a", "MEMBER_OF", "b", {"role": "owner"})
    bare = store.create_edge(abc, "a", "WORKS_ON", "c")
    assert bare.props == {}


def test_create_edge_upserts_one_edge_per_src_type_dst(store, abc):
    store.create_edge(abc, "a", "MEMBER_OF", "b", {"role": "member", "since": 2020})
    edge = store.create_edge(abc, "a", "MEMBER_OF", "b", {"role": "owner"})
    assert edge.props == {"role": "owner", "since": 2020}
    assert len(store.edges(abc)) == 1
    # direction and type are part of the identity
    store.create_edge(abc, "b", "MEMBER_OF", "a")
    store.create_edge(abc, "a", "OWNS", "b")
    assert len(store.edges(abc)) == 3


def test_edge_props_round_trip(store, abc):
    props = {"role": "owner", "n": 1, "meta": {"a": [1, None]}, "none": None, "tags": ["x"]}
    store.create_edge(abc, "a", "MEMBER_OF", "b", props)
    assert store.edges(abc, "a")[0].props == props


def test_create_edge_missing_endpoint_raises_not_found(store, abc):
    with pytest.raises(NotFound):
        store.create_edge(abc, "a", "MEMBER_OF", "nope")
    with pytest.raises(NotFound):
        store.create_edge(abc, "nope", "MEMBER_OF", "a")
    assert store.edges(abc) == []


def test_delete_edge(store, abc):
    store.create_edge(abc, "a", "MEMBER_OF", "b")
    store.create_edge(abc, "a", "OWNS", "b")
    assert store.delete_edge(abc, "b", "MEMBER_OF", "a") is False  # wrong direction
    assert store.delete_edge(abc, "a", "WORKS_ON", "b") is False  # wrong type
    assert store.delete_edge(abc, "a", "MEMBER_OF", "b") is True
    assert store.delete_edge(abc, "a", "MEMBER_OF", "b") is False
    assert [(e.src, e.type, e.dst) for e in store.edges(abc)] == [("a", "OWNS", "b")]
    assert store.get_node(abc, "a") is not None and store.get_node(abc, "b") is not None


def triples(edges) -> set[tuple[str, str, str]]:
    return {(e.src, e.type, e.dst) for e in edges}


@pytest.fixture
def linked(store, abc):
    store.create_edge(abc, "a", "MEMBER_OF", "b")
    store.create_edge(abc, "a", "WORKS_ON", "c")
    store.create_edge(abc, "b", "WORKS_ON", "c")
    store.create_edge(abc, "c", "REFERENCES", "a")
    return abc


def test_edges_directions(store, linked):
    assert triples(store.edges(linked, "a", direction="out")) == {
        ("a", "MEMBER_OF", "b"),
        ("a", "WORKS_ON", "c"),
    }
    assert triples(store.edges(linked, "a", direction="in")) == {("c", "REFERENCES", "a")}
    assert triples(store.edges(linked, "a")) == {
        ("a", "MEMBER_OF", "b"),
        ("a", "WORKS_ON", "c"),
        ("c", "REFERENCES", "a"),
    }
    assert store.edges(linked, "nope") == []


def test_edges_type_filter(store, linked):
    assert triples(store.edges(linked, type="WORKS_ON")) == {
        ("a", "WORKS_ON", "c"),
        ("b", "WORKS_ON", "c"),
    }
    assert triples(store.edges(linked, "c", "WORKS_ON", "in")) == {
        ("a", "WORKS_ON", "c"),
        ("b", "WORKS_ON", "c"),
    }
    assert store.edges(linked, "c", "WORKS_ON", "out") == []
    assert store.edges(linked, type="NOPE") == []


def test_edges_all_and_limit(store, linked):
    assert len(store.edges(linked)) == 4
    assert len(store.edges(linked, limit=2)) == 2
    assert len(store.edges(linked, "a", limit=2)) == 2
    assert len(store.edges(linked, "a", limit=10)) == 3


def test_self_loop_is_one_edge(store, abc):
    store.create_edge(abc, "a", "REFERENCES", "a")
    assert len(store.edges(abc, "a")) == 1
    assert len(store.edges(abc, "a", direction="out")) == 1
    assert len(store.edges(abc, "a", direction="in")) == 1
    assert ids(store.neighbors(abc, "a")) == ["a"]


# --- neighbors ---------------------------------------------------------------


def test_neighbors_directions_and_type(store, linked):
    assert sorted(ids(store.neighbors(linked, "a"))) == ["b", "c"]
    assert sorted(ids(store.neighbors(linked, "a", direction="out"))) == ["b", "c"]
    assert ids(store.neighbors(linked, "a", direction="in")) == ["c"]
    assert ids(store.neighbors(linked, "a", "MEMBER_OF")) == ["b"]
    assert sorted(ids(store.neighbors(linked, "c", "WORKS_ON", "in"))) == ["a", "b"]
    assert store.neighbors(linked, "c", "WORKS_ON", "out") == []
    assert store.neighbors(linked, "nope") == []


def test_neighbors_label_filter_and_dedup(store, linked):
    assert ids(store.neighbors(linked, "a", label="Team")) == ["b"]
    assert ids(store.neighbors(linked, "a", label="Project")) == ["c"]
    assert store.neighbors(linked, "a", label="Person") == []
    # c is reachable from a over two edges but is returned once, with its props
    both = store.neighbors(linked, "a")
    assert len(both) == 2
    assert {n.label for n in both} == {"Team", "Project"}
    assert all(n.props["id"] == n.id for n in both)


# --- counts / graph lifecycle -------------------------------------------------


def test_count_by_label(store, people):
    assert store.count_by_label(people) == {"Person": 4, "Team": 1}
    store.delete_node(people, "t1")
    assert store.count_by_label(people) == {"Person": 4}


def test_missing_graph_reads_are_empty(store, new_graph):
    missing = new_graph()
    assert store.get_node(missing, "x") is None
    assert store.find_nodes(missing) == []
    assert store.find_nodes(missing, "Person", {"a": 1}, order_by="a", limit=3) == []
    assert store.edges(missing) == []
    assert store.edges(missing, "x") == []
    assert store.neighbors(missing, "x") == []
    assert store.count_by_label(missing) == {}
    assert store.delete_node(missing, "x") is False
    assert store.delete_edge(missing, "a", "T", "b") is False
    store.delete_graph(missing)  # deleting a graph that does not exist is a no-op


def test_delete_graph(store, g):
    store.create_node(g, "T", {"id": "a"})
    store.create_node(g, "T", {"id": "b"})
    store.create_edge(g, "a", "LINKS", "b")
    store.delete_graph(g)
    assert store.find_nodes(g) == []
    assert store.edges(g) == []
    assert store.count_by_label(g) == {}
    # the graph is usable again afterwards, including a previously used id
    store.create_node(g, "T", {"id": "a"})
    assert ids(store.find_nodes(g, "T")) == ["a"]


def test_graphs_are_isolated(store, new_graph):
    g1, g2 = new_graph(), new_graph()
    store.create_node(g1, "T", {"id": "a", "where": "g1"})
    store.create_node(g2, "T", {"id": "a", "where": "g2"})  # same id, different graph
    store.create_node(g1, "T", {"id": "b"})
    store.create_edge(g1, "a", "LINKS", "b")
    assert store.get_node(g1, "a").props["where"] == "g1"
    assert store.get_node(g2, "a").props["where"] == "g2"
    assert store.get_node(g2, "b") is None
    assert store.edges(g2) == []
    with pytest.raises(NotFound):
        store.create_edge(g2, "a", "LINKS", "b")
    store.delete_graph(g1)
    assert ids(store.find_nodes(g2)) == ["a"]
