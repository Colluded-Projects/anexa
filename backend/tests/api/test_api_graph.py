import os

import pytest

from anexa.store import MemoryStore, StoreError

memory_only = pytest.mark.skipif(
    bool(os.environ.get("ANEXA_TEST_FALKOR_LITE")), reason="stubs MemoryStore.query"
)


def test_ontology(client, ada):
    body = client.get(f"{ada.base}/graph/ontology", headers=ada.headers).json()
    assert set(body) == {"node_labels", "edge_types"}
    assert "Person" in body["node_labels"] and "Decision" in body["node_labels"]
    assert "MEMBER_OF" in body["edge_types"]


def test_create_node_defaults(client, ada, make):
    node = make.node(ada, "Person", "Grace Hopper", props={"title": "Admiral", "url": "https://x"})
    assert set(node) == {"id", "label", "name", "key", "source", "url", "props", "updated_at"}
    assert node["label"] == "Person" and node["name"] == "Grace Hopper"
    assert node["key"] == f"manual:{node['id']}" and node["source"] == "manual"
    assert node["url"] == "https://x" and node["props"] == {"title": "Admiral"}
    assert node["updated_at"]

    keyed = make.node(ada, "Team", "Platform", key="team:platform")
    assert keyed["key"] == "team:platform" and keyed["url"] is None and keyed["props"] == {}


def test_create_node_validation(client, ada, make):
    url = f"{ada.base}/graph/nodes"
    bad = client.post(url, json={"label": "Alien", "name": "x"}, headers=ada.headers)
    assert bad.status_code == 422 and "Alien" in bad.json()["detail"]
    assert client.post(url, json={"label": "Person"}, headers=ada.headers).status_code == 422
    make.node(ada, "Team", "Platform", key="team:platform")
    dup = client.post(
        url, json={"label": "Team", "name": "Again", "key": "team:platform"}, headers=ada.headers
    )
    assert dup.status_code == 409
    # the same key under another label is a different entity
    make.node(ada, "Project", "Platform", key="team:platform")


def test_props_cannot_override_identity(client, ada, make):
    node = make.node(
        ada, props={"id": "evil", "key": "evil", "source": "evil", "label": "Team", "ok": 1}
    )
    assert node["id"] != "evil" and node["source"] == "manual" and node["label"] == "Person"
    assert node["key"].startswith("manual:") and node["props"] == {"ok": 1}
    r = client.patch(
        f"{ada.base}/graph/nodes/{node['id']}",
        json={"props": {"id": "evil", "source": "evil", "key": "evil"}},
        headers=ada.headers,
    ).json()
    assert r["id"] == node["id"] and r["source"] == "manual" and r["key"] == node["key"]


def test_list_and_search_nodes(client, ada, make):
    make.node(ada, "Person", "Grace Hopper")
    make.node(ada, "Person", "Alan Turing")
    make.node(ada, "Team", "Grace period team")

    def names(query=""):
        r = client.get(f"{ada.base}/graph/nodes{query}", headers=ada.headers)
        assert r.status_code == 200
        return [n["name"] for n in r.json()]

    assert names() == ["Alan Turing", "Grace Hopper", "Grace period team"]
    assert names("?label=Person") == ["Alan Turing", "Grace Hopper"]
    assert names("?q=gRaCe") == ["Grace Hopper", "Grace period team"]
    assert names("?label=Team&q=grace") == ["Grace period team"]
    assert len(names("?limit=1")) == 1
    assert client.get(f"{ada.base}/graph/nodes?label=Alien", headers=ada.headers).status_code == 422
    assert client.get(f"{ada.base}/graph/nodes?limit=501", headers=ada.headers).status_code == 422


def test_node_detail_update_delete(client, ada, make):
    grace = make.node(ada, "Person", "Grace", props={"title": "Admiral", "level": 3})
    team = make.node(ada, "Team", "Platform")
    edge = client.post(
        f"{ada.base}/graph/edges",
        json={"src": grace["id"], "type": "MEMBER_OF", "dst": team["id"], "props": {"since": 2020}},
        headers=ada.headers,
    )
    assert edge.status_code == 201
    assert edge.json() == {
        "src": grace["id"],
        "type": "MEMBER_OF",
        "dst": team["id"],
        "props": {"since": 2020, "source": "manual"},
    }

    url = f"{ada.base}/graph/nodes/{grace['id']}"
    detail = client.get(url, headers=ada.headers).json()
    assert detail["name"] == "Grace"
    assert detail["edges"] == [edge.json()]
    assert [n["id"] for n in detail["neighbors"]] == [team["id"]]
    team_detail = client.get(f"{ada.base}/graph/nodes/{team['id']}", headers=ada.headers).json()
    assert [n["name"] for n in team_detail["neighbors"]] == ["Grace"]

    r = client.patch(
        url,
        json={"name": "Grace H.", "props": {"title": "Rear Admiral", "url": "https://g"}},
        headers=ada.headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Grace H." and r.json()["url"] == "https://g"
    assert r.json()["props"] == {"title": "Rear Admiral", "level": 3}
    assert r.json()["updated_at"] >= grace["updated_at"]
    # null removes a property from the response
    r = client.patch(url, json={"props": {"level": None}}, headers=ada.headers)
    assert r.json()["props"] == {"title": "Rear Admiral"}

    assert client.delete(url, headers=ada.headers).status_code == 204
    assert client.get(url, headers=ada.headers).status_code == 404
    assert client.patch(url, json={"name": "x"}, headers=ada.headers).status_code == 404
    assert client.delete(url, headers=ada.headers).status_code == 404
    # its edges went with it
    assert (
        client.get(f"{ada.base}/graph/nodes/{team['id']}", headers=ada.headers).json()["edges"]
        == []
    )


def test_edges(client, ada, make):
    a, b = make.node(ada, "Person", "A"), make.node(ada, "Project", "B")
    url = f"{ada.base}/graph/edges"
    bad_type = client.post(
        url, json={"src": a["id"], "type": "LOVES", "dst": b["id"]}, headers=ada.headers
    )
    assert bad_type.status_code == 422
    missing = client.post(
        url, json={"src": a["id"], "type": "WORKS_ON", "dst": "missing"}, headers=ada.headers
    )
    assert missing.status_code == 404
    assert (
        client.post(
            url, json={"src": a["id"], "type": "WORKS_ON", "dst": b["id"]}, headers=ada.headers
        ).status_code
        == 201
    )

    params = {"src": a["id"], "type": "WORKS_ON", "dst": b["id"]}
    assert client.delete(url, params=params, headers=ada.headers).status_code == 204
    assert client.delete(url, params=params, headers=ada.headers).status_code == 404
    assert client.delete(url, params={"src": a["id"]}, headers=ada.headers).status_code == 422


def test_subgraph_and_stats(client, ada, make):
    p = make.node(ada, "Person", "P")
    t = make.node(ada, "Team", "T")
    j = make.node(ada, "Project", "J")
    for src, type_, dst in ((p, "MEMBER_OF", t), (t, "WORKS_ON", j)):
        client.post(
            f"{ada.base}/graph/edges",
            json={"src": src["id"], "type": type_, "dst": dst["id"]},
            headers=ada.headers,
        )

    stats = client.get(f"{ada.base}/graph/stats", headers=ada.headers).json()
    assert stats == {
        "nodes": {"Person": 1, "Team": 1, "Project": 1},
        "total_nodes": 3,
        "total_edges": 2,
    }

    full = client.get(f"{ada.base}/graph/subgraph", headers=ada.headers).json()
    assert {n["id"] for n in full["nodes"]} == {p["id"], t["id"], j["id"]}
    assert {(e["src"], e["type"], e["dst"]) for e in full["edges"]} == {
        (p["id"], "MEMBER_OF", t["id"]),
        (t["id"], "WORKS_ON", j["id"]),
    }
    # only edges between returned nodes
    people = client.get(f"{ada.base}/graph/subgraph?label=Person", headers=ada.headers).json()
    assert [n["id"] for n in people["nodes"]] == [p["id"]] and people["edges"] == []
    limited = client.get(f"{ada.base}/graph/subgraph?limit=2", headers=ada.headers).json()
    assert len(limited["nodes"]) == 2
    ids = {n["id"] for n in limited["nodes"]}
    assert all(e["src"] in ids and e["dst"] in ids for e in limited["edges"])
    assert (
        client.get(f"{ada.base}/graph/subgraph?limit=1001", headers=ada.headers).status_code == 422
    )


def test_empty_graph(client, ada):
    assert client.get(f"{ada.base}/graph/nodes", headers=ada.headers).json() == []
    assert client.get(f"{ada.base}/graph/subgraph", headers=ada.headers).json() == {
        "nodes": [],
        "edges": [],
    }
    assert client.get(f"{ada.base}/graph/stats", headers=ada.headers).json() == {
        "nodes": {},
        "total_nodes": 0,
        "total_edges": 0,
    }


@memory_only
def test_query_is_501_on_memory_backend(client, ada):
    r = client.post(
        f"{ada.base}/graph/query", json={"cypher": "MATCH (n) RETURN n"}, headers=ada.headers
    )
    assert r.status_code == 501 and isinstance(r.json()["detail"], str)


@memory_only
@pytest.mark.parametrize("error", [StoreError("syntax error near FOO"), RuntimeError("bad query")])
def test_query_runs_readonly_against_workspace_graph(client, ada, monkeypatch, settings, error):
    calls = []

    def fake_query(self, graph, cypher, params=None, *, readonly=True):
        calls.append((graph, cypher, params, readonly))
        if "FOO" in cypher:
            raise error
        return [{"name": "Grace", "n": 1}]

    monkeypatch.setattr(MemoryStore, "query", fake_query)
    url = f"{ada.base}/graph/query"
    ok = client.post(
        url,
        json={"cypher": "MATCH (p:Person) RETURN p.name AS name", "params": {"x": 1}},
        headers=ada.headers,
    )
    assert ok.status_code == 200 and ok.json() == {"rows": [{"name": "Grace", "n": 1}]}
    assert calls == [
        (settings.company_graph(ada.ws), "MATCH (p:Person) RETURN p.name AS name", {"x": 1}, True)
    ]
    bad = client.post(url, json={"cypher": "FOO"}, headers=ada.headers)
    assert bad.status_code == 422 and isinstance(bad.json()["detail"], str)


def test_graphs_are_isolated_per_workspace(client, ada, bob, make):
    node = make.node(ada, "Person", "Secret Person")
    assert client.get(f"{bob.base}/graph/nodes", headers=bob.headers).json() == []
    assert (
        client.get(f"{bob.base}/graph/nodes/{node['id']}", headers=bob.headers).status_code == 404
    )
    assert (
        client.patch(
            f"{bob.base}/graph/nodes/{node['id']}", json={"name": "x"}, headers=bob.headers
        ).status_code
        == 404
    )
    assert (
        client.delete(f"{bob.base}/graph/nodes/{node['id']}", headers=bob.headers).status_code
        == 404
    )
    mine = make.node(bob, "Person", "Bob's")
    cross = client.post(
        f"{bob.base}/graph/edges",
        json={"src": mine["id"], "type": "REPORTS_TO", "dst": node["id"]},
        headers=bob.headers,
    )
    assert cross.status_code == 404
    for path in ("nodes", "stats", "subgraph", "ontology", f"nodes/{node['id']}"):
        assert client.get(f"{ada.base}/graph/{path}", headers=bob.headers).status_code == 403
    # the platform graph (users, credentials) is not reachable through node ids
    assert (
        client.get(f"{ada.base}/graph/nodes/{ada.user['id']}", headers=ada.headers).status_code
        == 404
    )
