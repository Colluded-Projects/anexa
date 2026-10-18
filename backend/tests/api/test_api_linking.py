from anexa.graph.demo import GOLD
from anexa.graph.linking import STRATEGY


def test_demo_link_and_score(client, ada):
    base, h = f"{ada.base}/graph", ada.headers

    loaded = client.post(f"{base}/demo", headers=h)
    assert loaded.status_code == 201
    assert set(loaded.json()["loaded"]) == {"slack", "jira", "github", "google"}
    assert client.get(f"{base}/stats", headers=h).json()["nodes"]["Message"] == 5

    linked = client.post(f"{base}/link", headers=h)
    assert linked.status_code == 200
    assert linked.json()["strategy"] == STRATEGY

    result = client.get(f"{base}/link/score", headers=h).json()
    assert set(result) == set(GOLD)
    assert {"precision", "recall", "expected", "found", "correct"} <= set(result["references"])


def test_experts_by_topic(client, ada):
    base, h = f"{ada.base}/graph", ada.headers
    client.post(f"{base}/demo", headers=h)
    client.post(f"{base}/link", headers=h)

    found = client.get(f"{base}/experts", params={"topic": "kafka"}, headers=h)
    assert found.status_code == 200
    names = [e["name"] for e in found.json()]
    assert "Ada Lovelace" in names and "Bob Stone" in names
    assert {"name", "key", "score"} == set(found.json()[0])
    assert client.get(f"{base}/experts", params={"topic": "nope"}, headers=h).json() == []


def test_linking_is_per_workspace(client, ada, bob):
    client.post(f"{ada.base}/graph/demo", headers=ada.headers)
    assert client.get(f"{bob.base}/graph/stats", headers=bob.headers).json()["total_nodes"] == 0


def test_linking_needs_auth(client, ada):
    assert client.post(f"{ada.base}/graph/link").status_code == 401
