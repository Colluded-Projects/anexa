"""Storage contract.

Everything the platform persists goes through `GraphStore`, a small property
graph interface. `FalkorStore` implements it with Cypher against FalkorDB and
`MemoryStore` implements it in-process for tests. Both must pass the same
contract test-suite (tests/store/test_contract.py).

Rules shared by every implementation:

* A node has exactly one label and a string `id` (generated when not supplied)
  that is unique within its graph. `id` is also present inside `props`.
* Property values are JSON-serialisable. Scalars (str, int, float, bool) and
  lists of scalars are stored natively and can be filtered on; dicts, nested
  lists and None are round-tripped faithfully but are not filterable.
* There is at most one edge per (src, type, dst); `create_edge` upserts it.
* Graphs are created lazily on first write; reading a missing graph returns
  empty results rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Direction = Literal["out", "in", "both"]


class StoreError(Exception):
    pass


class NotFound(StoreError):
    pass


@dataclass
class Node:
    id: str
    label: str
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    type: str
    dst: str
    props: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GraphStore(Protocol):
    def create_node(self, graph: str, label: str, props: dict[str, Any]) -> Node:
        """Create a node. Uses props["id"] when given, else generates one.
        Raises StoreError if a node with that id already exists in the graph."""

    def get_node(self, graph: str, node_id: str, label: str | None = None) -> Node | None: ...

    def find_nodes(
        self,
        graph: str,
        label: str | None = None,
        where: dict[str, Any] | None = None,
        *,
        contains: dict[str, str] | None = None,
        order_by: str | None = None,
        desc: bool = False,
        skip: int = 0,
        limit: int | None = None,
    ) -> list[Node]:
        """`where` is exact-match on scalar props (all must match). `contains`
        is case-insensitive substring match on string props (all must match).
        Nodes missing the `order_by` prop sort last."""

    def update_node(self, graph: str, node_id: str, props: dict[str, Any]) -> Node:
        """Merge `props` into the node (keys set to None are stored as None).
        `id` cannot be changed. Raises NotFound."""

    def delete_node(self, graph: str, node_id: str) -> bool:
        """Delete the node and all its edges. Returns False if it did not exist."""

    def upsert_node(
        self, graph: str, label: str, key: dict[str, Any], props: dict[str, Any]
    ) -> Node:
        """Find the node of `label` matching every scalar in `key`; merge `props`
        into it, or create it with key+props."""

    def create_edge(
        self, graph: str, src: str, type: str, dst: str, props: dict[str, Any] | None = None
    ) -> Edge:
        """Upsert the (src)-[type]->(dst) edge. Raises NotFound if either node is missing."""

    def delete_edge(self, graph: str, src: str, type: str, dst: str) -> bool: ...

    def edges(
        self,
        graph: str,
        node_id: str | None = None,
        type: str | None = None,
        direction: Direction = "both",
        limit: int | None = None,
    ) -> list[Edge]:
        """Edges touching `node_id` in `direction` (all edges when node_id is None)."""

    def neighbors(
        self,
        graph: str,
        node_id: str,
        type: str | None = None,
        direction: Direction = "both",
        label: str | None = None,
    ) -> list[Node]: ...

    def count_by_label(self, graph: str) -> dict[str, int]: ...

    def query(
        self,
        graph: str,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        readonly: bool = True,
    ) -> list[dict[str, Any]]:
        """Raw Cypher escape hatch. Rows are dicts keyed by column name; node and
        edge values are converted to plain dicts. MemoryStore raises
        NotImplementedError."""

    def delete_graph(self, graph: str) -> None: ...
