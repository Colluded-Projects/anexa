from __future__ import annotations

import copy
import threading
import uuid
from typing import Any

from .base import Direction, Edge, Node, NotFound, StoreError


class _Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[tuple[str, str, str], Edge] = {}


class MemoryStore:
    """In-process GraphStore used by tests and single-process demos."""

    def __init__(self) -> None:
        self._graphs: dict[str, _Graph] = {}
        self._lock = threading.RLock()

    def _g(self, graph: str) -> _Graph:
        return self._graphs.setdefault(graph, _Graph())

    @staticmethod
    def _copy(node: Node) -> Node:
        return Node(node.id, node.label, copy.deepcopy(node.props))

    def create_node(self, graph: str, label: str, props: dict[str, Any]) -> Node:
        with self._lock:
            g = self._g(graph)
            node_id = str(props.get("id") or uuid.uuid4().hex)
            if node_id in g.nodes:
                raise StoreError(f"node {node_id!r} already exists in graph {graph!r}")
            node = Node(node_id, label, {**copy.deepcopy(props), "id": node_id})
            g.nodes[node_id] = node
            return self._copy(node)

    def get_node(self, graph: str, node_id: str, label: str | None = None) -> Node | None:
        with self._lock:
            node = self._g(graph).nodes.get(node_id)
            if node is None or (label is not None and node.label != label):
                return None
            return self._copy(node)

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
        with self._lock:
            out = []
            for node in self._g(graph).nodes.values():
                if label is not None and node.label != label:
                    continue
                if where and any(node.props.get(k) != v for k, v in where.items()):
                    continue
                if contains and not all(
                    isinstance(node.props.get(k), str) and v.lower() in node.props[k].lower()
                    for k, v in contains.items()
                ):
                    continue
                out.append(node)
            if order_by:
                present = [n for n in out if n.props.get(order_by) is not None]
                missing = [n for n in out if n.props.get(order_by) is None]
                present.sort(key=lambda n: n.props[order_by], reverse=desc)
                out = present + missing
            out = out[skip:] if limit is None else out[skip : skip + limit]
            return [self._copy(n) for n in out]

    def update_node(self, graph: str, node_id: str, props: dict[str, Any]) -> Node:
        with self._lock:
            node = self._g(graph).nodes.get(node_id)
            if node is None:
                raise NotFound(f"node {node_id!r} not found in graph {graph!r}")
            node.props.update(copy.deepcopy({k: v for k, v in props.items() if k != "id"}))
            return self._copy(node)

    def delete_node(self, graph: str, node_id: str) -> bool:
        with self._lock:
            g = self._g(graph)
            if g.nodes.pop(node_id, None) is None:
                return False
            for key in [k for k in g.edges if node_id in (k[0], k[2])]:
                del g.edges[key]
            return True

    def upsert_node(
        self, graph: str, label: str, key: dict[str, Any], props: dict[str, Any]
    ) -> Node:
        with self._lock:
            found = self.find_nodes(graph, label, key, limit=1)
            if found:
                return self.update_node(graph, found[0].id, props)
            return self.create_node(graph, label, {**props, **key})

    def create_edge(
        self, graph: str, src: str, type: str, dst: str, props: dict[str, Any] | None = None
    ) -> Edge:
        with self._lock:
            g = self._g(graph)
            for node_id in (src, dst):
                if node_id not in g.nodes:
                    raise NotFound(f"node {node_id!r} not found in graph {graph!r}")
            edge = g.edges.setdefault((src, type, dst), Edge(src, type, dst, {}))
            edge.props.update(copy.deepcopy(props or {}))
            return copy.deepcopy(edge)

    def delete_edge(self, graph: str, src: str, type: str, dst: str) -> bool:
        with self._lock:
            return self._g(graph).edges.pop((src, type, dst), None) is not None

    def edges(
        self,
        graph: str,
        node_id: str | None = None,
        type: str | None = None,
        direction: Direction = "both",
        limit: int | None = None,
    ) -> list[Edge]:
        with self._lock:
            out = []
            for edge in self._g(graph).edges.values():
                if type is not None and edge.type != type:
                    continue
                if node_id is not None:
                    is_out, is_in = edge.src == node_id, edge.dst == node_id
                    if not (
                        (direction in ("out", "both") and is_out)
                        or (direction in ("in", "both") and is_in)
                    ):
                        continue
                out.append(copy.deepcopy(edge))
                if limit is not None and len(out) >= limit:
                    break
            return out

    def neighbors(
        self,
        graph: str,
        node_id: str,
        type: str | None = None,
        direction: Direction = "both",
        label: str | None = None,
    ) -> list[Node]:
        with self._lock:
            g = self._g(graph)
            seen: dict[str, Node] = {}
            for edge in self.edges(graph, node_id, type, direction):
                for other in {edge.src, edge.dst} - {node_id} or {node_id}:
                    node = g.nodes.get(other)
                    if node is not None and (label is None or node.label == label):
                        seen.setdefault(other, self._copy(node))
            return list(seen.values())

    def count_by_label(self, graph: str) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for node in self._g(graph).nodes.values():
                counts[node.label] = counts.get(node.label, 0) + 1
            return counts

    def query(
        self,
        graph: str,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        readonly: bool = True,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("raw Cypher needs the FalkorDB backend")

    def delete_graph(self, graph: str) -> None:
        with self._lock:
            self._graphs.pop(graph, None)
