import pytest

from orgraph.connectors.agent import AgentConnector
from orgraph.connectors.base import ConnectorError

agent = AgentConnector()


def test_spec():
    spec = agent.spec
    assert spec.key == "agent"
    fields = {f.name: f for f in spec.config_fields}
    assert fields["provider"].type == "select"
    assert fields["provider"].options == ["claude_code", "openrouter", "jev", "custom"]
    assert fields["api_key"].secret and not fields["api_key"].required
    assert [op.name for op in spec.operations] == ["invoke"]
    assert spec.operations[0].kind == "action"


def test_invoke_reports_not_connected_and_makes_no_request(make_ctx, respx_mock):
    ctx = make_ctx(config={"provider": "jev", "model": "jev-1"}, secrets={"api_key": "sk-secret"})
    result = agent.execute("invoke", {"prompt": "Summarise the week", "context": "notes"}, ctx)

    assert result.output == {
        "status": "not_connected",
        "provider": "jev",
        "model": "jev-1",
        "prompt": "Summarise the week",
        "context": "notes",
        "message": "No agent runtime is connected yet.",
    }
    assert result.graph is None
    assert not respx_mock.calls
    assert "sk-secret" not in str(result.output)


def test_invoke_defaults(make_ctx):
    result = agent.execute("invoke", {"prompt": "hi"}, make_ctx())
    assert result.output == {
        "status": "not_connected",
        "provider": "claude_code",
        "model": "",
        "prompt": "hi",
        "message": "No agent runtime is connected yet.",
    }


def test_invoke_requires_prompt_and_rejects_unknown_operation(make_ctx):
    with pytest.raises(ConnectorError, match="prompt"):
        agent.execute("invoke", {}, make_ctx())
    with pytest.raises(ConnectorError, match="no operation"):
        agent.execute("chat", {"prompt": "hi"}, make_ctx())


def test_test_does_not_raise(make_ctx, respx_mock):
    assert agent.test(make_ctx(config={"provider": "openrouter"})) == {
        "status": "not_connected",
        "provider": "openrouter",
        "model": "",
        "message": "No agent runtime is connected yet.",
    }
    assert not respx_mock.calls
