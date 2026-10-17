import httpx
import pytest

from orgraph.connectors.base import ConnectorContext, GraphDelta


@pytest.fixture
def make_ctx():
    """Build a ConnectorContext with a real httpx.Client (intercepted by respx)."""
    clients = []

    def _make(config=None, secrets=None):
        client = httpx.Client()
        clients.append(client)
        return ConnectorContext(config=config or {}, secrets=secrets or {}, http=client)

    yield _make
    for client in clients:
        client.close()


class Delta:
    """Lookups over a GraphDelta for assertions."""

    def __init__(self, delta: GraphDelta | None):
        assert delta is not None, "operation returned no GraphDelta"
        self.delta = delta

    def node(self, label, key):
        matches = [n for n in self.delta.nodes if n.label == label and n.key == key]
        assert len(matches) == 1, f"expected one {label} {key!r}, found {len(matches)}"
        return matches[0]

    def keys(self, label):
        return sorted(n.key for n in self.delta.nodes if n.label == label)

    def edges(self, type=None):
        return sorted(
            (e.src_label, e.src_key, e.type, e.dst_label, e.dst_key)
            for e in self.delta.edges
            if type is None or e.type == type
        )


@pytest.fixture
def delta_of():
    return Delta
