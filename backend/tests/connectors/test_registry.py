import pytest

from orgraph.connectors import ConnectorError, all_specs, get_connector
from orgraph.graph.ontology import EDGE_TYPES, NODE_LABELS  # noqa: F401

BUILTIN = ["agent", "github", "google", "jira", "slack"]


def test_builtin_connectors_are_registered():
    assert sorted(spec.key for spec in all_specs()) == BUILTIN
    for key in BUILTIN:
        assert get_connector(key).spec.key == key


def test_unknown_connector():
    with pytest.raises(ConnectorError, match="unknown connector"):
        get_connector("carrier-pigeon")


@pytest.mark.parametrize("key", BUILTIN)
def test_spec_is_well_formed(key):
    connector = get_connector(key)
    spec = connector.spec
    assert spec.title and spec.description

    names = [f.name for f in spec.config_fields]
    assert len(names) == len(set(names))
    for field in spec.config_fields:
        assert field.label
        if field.type == "select":
            assert field.options

    op_names = [op.name for op in spec.operations]
    assert op_names and len(op_names) == len(set(op_names))
    for op in spec.operations:
        assert op.title
        # every declared operation has an implementation
        assert key == "agent" or callable(getattr(connector, f"_op_{op.name}"))
        params = [p.name for p in op.params]
        assert len(params) == len(set(params))
        assert not any(p.secret for p in op.params)
