from orgraph.connectors.base import GraphDelta, NodeUpsert
from orgraph.graph.ingest import apply_delta


def test_connector_props_cannot_overwrite_identity(store):
    props = {"id": "evil", "key": "evil", "name": "A", "display-name": "Ada"}
    delta = GraphDelta(nodes=[NodeUpsert(label="Person", key="email:a@x.io", props=props)])

    apply_delta(store, "g", delta, "slack")

    (node,) = store.find_nodes("g", "Person")
    assert node.props["key"] == "email:a@x.io"
    assert node.id != "evil" and node.props["id"] == node.id
    # FalkorDB property names must be identifiers.
    assert node.props["display_name"] == "Ada"
