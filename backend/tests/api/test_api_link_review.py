"""Review queue: unsure linker edges wait for a human to accept or reject them."""


def linker_edge(client, who, src, dst, confidence, type="RELATED_TO"):
    props = {"source": "linker", "method": "llm", "confidence": confidence, "evidence": "login"}
    body = {"src": src, "type": type, "dst": dst, "props": props}
    assert client.post(f"{who.base}/graph/edges", json=body, headers=who.headers).status_code == 201


def setup(client, who, make):
    a = make.node(who, label="Message", name="login is slow")
    b = make.node(who, label="Ticket", name="ENG-15")
    c = make.node(who, label="Ticket", name="API-7")
    linker_edge(client, who, a["id"], b["id"], 0.4)
    linker_edge(client, who, a["id"], c["id"], 0.9)
    # a manual edge is never reviewed
    body = {"src": b["id"], "type": "REFERENCES", "dst": c["id"], "props": {"confidence": 0.1}}
    client.post(f"{who.base}/graph/edges", json=body, headers=who.headers)
    return a, b, c


def test_review_lists_unsure_linker_edges(client, ada, make):
    a, b, _ = setup(client, ada, make)
    rows = client.get(f"{ada.base}/graph/link/review", headers=ada.headers).json()
    assert rows == [
        {
            "src": a["id"], "src_name": "login is slow", "type": "RELATED_TO",
            "dst": b["id"], "dst_name": "ENG-15",
            "method": "llm", "confidence": 0.4, "evidence": "login",
        }
    ]


def test_accept_marks_edge_human_checked(client, ada, make):
    a, b, _ = setup(client, ada, make)
    body = {"src": a["id"], "type": "RELATED_TO", "dst": b["id"]}
    accepted = client.post(f"{ada.base}/graph/link/review/accept", json=body, headers=ada.headers)
    assert accepted.status_code == 200
    assert accepted.json()["props"]["confidence"] == 1.0
    assert accepted.json()["props"]["method"] == "llm+human"
    assert client.get(f"{ada.base}/graph/link/review", headers=ada.headers).json() == []


def test_accept_unknown_edge_is_404(client, ada, make):
    a, b, _ = setup(client, ada, make)
    body = {"src": b["id"], "type": "RELATED_TO", "dst": a["id"]}
    accepted = client.post(f"{ada.base}/graph/link/review/accept", json=body, headers=ada.headers)
    assert accepted.status_code == 404


def test_reject_deletes_the_edge(client, ada, make):
    a, b, _ = setup(client, ada, make)
    query = {"src": a["id"], "type": "RELATED_TO", "dst": b["id"]}
    deleted = client.delete(f"{ada.base}/graph/edges", params=query, headers=ada.headers)
    assert deleted.status_code == 204
    assert client.get(f"{ada.base}/graph/link/review", headers=ada.headers).json() == []


def test_link_reports_llm_off(client, ada):
    client.post(f"{ada.base}/graph/demo", headers=ada.headers)
    linked = client.post(f"{ada.base}/graph/link", headers=ada.headers).json()
    assert linked["llm"] == "off"
