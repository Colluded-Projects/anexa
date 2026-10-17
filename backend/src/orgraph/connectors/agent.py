"""Placeholder connector for a future AI agent. It never touches the network:
no agent runtime exists yet, so every call reports "not_connected"."""

from __future__ import annotations

from typing import Any

from . import register
from .base import (
    Connector,
    ConnectorContext,
    ConnectorSpec,
    FieldSpec,
    OperationResult,
    OperationSpec,
)

PROVIDERS = ["claude_code", "openrouter", "jev", "custom"]
NOT_CONNECTED_MESSAGE = "No agent runtime is connected yet."


class AgentConnector(Connector):
    spec = ConnectorSpec(
        key="agent",
        title="Agent",
        description="Placeholder for an AI agent. Calls are recorded but nothing is invoked yet.",
        config_fields=[
            FieldSpec(
                name="provider",
                label="Provider",
                type="select",
                options=PROVIDERS,
                default="claude_code",
                help="Which runtime this agent will use once one is connected.",
            ),
            FieldSpec(name="model", label="Model", placeholder="claude-opus-5-5"),
            FieldSpec(
                name="api_key",
                label="API key",
                secret=True,
                help="Optional. Stored encrypted for later use; not used today.",
            ),
        ],
        operations=[
            OperationSpec(
                name="invoke",
                title="Invoke agent",
                description="Hand a prompt to the agent. Returns not_connected until a runtime "
                "is attached.",
                params=[
                    FieldSpec(name="prompt", label="Prompt", type="text", required=True),
                    FieldSpec(
                        name="context",
                        label="Context",
                        type="text",
                        help="Extra data for the agent, e.g. the output of an earlier task.",
                    ),
                ],
            )
        ],
    )

    def _status(self, ctx: ConnectorContext) -> dict[str, Any]:
        return {
            "status": "not_connected",
            "provider": ctx.config.get("provider") or "claude_code",
            "model": ctx.config.get("model") or "",
            "message": NOT_CONNECTED_MESSAGE,
        }

    def execute(
        self, operation: str, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        self.validate_params(operation, params)
        output = {**self._status(ctx), "prompt": params["prompt"]}
        if params.get("context") not in (None, ""):
            output["context"] = params["context"]
        return OperationResult(output=output)

    def test(self, ctx: ConnectorContext) -> dict[str, Any]:
        return self._status(ctx)


register(AgentConnector())
