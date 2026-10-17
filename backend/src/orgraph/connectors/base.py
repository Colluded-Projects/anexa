"""Connector contract.

A connector wraps one external system. It declares the fields a Connection
needs (`config_fields`) and the operations Actions can call. Operations are
synchronous and receive a ready `httpx.Client`; they must not read settings or
the store themselves. "sync" operations additionally return a GraphDelta that
the engine merges into the workspace's company graph.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

import httpx
from pydantic import BaseModel, Field


class ConnectorError(Exception):
    """Operation failed in a way worth showing to the user (bad credentials,
    API error, invalid params). The message is stored on the run."""


class FieldSpec(BaseModel):
    name: str
    label: str
    type: Literal["string", "text", "number", "boolean", "select"] = "string"
    required: bool = False
    secret: bool = False  # stored encrypted, never returned by the API
    help: str = ""
    default: Any = None
    options: list[str] = Field(default_factory=list)  # for type="select"
    placeholder: str = ""


class OperationSpec(BaseModel):
    name: str
    title: str
    description: str = ""
    kind: Literal["action", "sync"] = "action"  # "sync" writes into the company graph
    params: list[FieldSpec] = Field(default_factory=list)


class ConnectorSpec(BaseModel):
    key: str
    title: str
    description: str = ""
    config_fields: list[FieldSpec] = Field(default_factory=list)
    operations: list[OperationSpec] = Field(default_factory=list)

    def operation(self, name: str) -> OperationSpec | None:
        return next((op for op in self.operations if op.name == name), None)


class NodeUpsert(BaseModel):
    label: str  # one of graph.ontology.NODE_LABELS
    key: str  # stable identity within the label, see graph.ontology.entity_key
    props: dict[str, Any] = Field(default_factory=dict)


class EdgeUpsert(BaseModel):
    src_label: str
    src_key: str
    type: str  # one of graph.ontology.EDGE_TYPES
    dst_label: str
    dst_key: str
    props: dict[str, Any] = Field(default_factory=dict)


class GraphDelta(BaseModel):
    nodes: list[NodeUpsert] = Field(default_factory=list)
    edges: list[EdgeUpsert] = Field(default_factory=list)


class OperationResult(BaseModel):
    output: dict[str, Any] = Field(default_factory=dict)
    graph: GraphDelta | None = None


@dataclass
class ConnectorContext:
    config: dict[str, Any]
    secrets: dict[str, Any]
    http: httpx.Client
    extras: dict[str, Any] = field(default_factory=dict)


class Connector(ABC):
    spec: ClassVar[ConnectorSpec]

    @abstractmethod
    def execute(
        self, operation: str, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        """Run `operation`. Raise ConnectorError for user-facing failures."""

    @abstractmethod
    def test(self, ctx: ConnectorContext) -> dict[str, Any]:
        """Verify the credentials with a cheap API call and return a small
        description of the authenticated identity. Raise ConnectorError on failure."""

    def validate_params(self, operation: str, params: dict[str, Any]) -> None:
        op = self.spec.operation(operation)
        if op is None:
            raise ConnectorError(f"{self.spec.key} has no operation {operation!r}")
        missing = [f.name for f in op.params if f.required and params.get(f.name) in (None, "")]
        if missing:
            raise ConnectorError(f"missing required params: {', '.join(missing)}")
