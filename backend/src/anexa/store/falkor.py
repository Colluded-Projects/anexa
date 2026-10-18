"""GraphStore on FalkorDB.

Values always travel as query parameters. Labels, edge types and property
names cannot be parameters in Cypher (and the client writes parameter-map keys
into the query text unquoted), so every one of them is checked against
`_IDENT` before it gets near a query.

FalkorDB properties hold scalars and arrays only. Anything else (dict, nested
or mixed list, None) is stored as a JSON string behind `_TAG` and decoded on
read; scalars and same-typed lists of scalars stay native so they can be
filtered on.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from typing import Any

from ..config import Settings
from .base import Direction, Edge, Node, NotFound, StoreError

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TAG = "@@json:"
_NULL = _TAG + "null"
_SCALARS = (str, bool, int, float)

_NODE_COLUMNS = "labels(n)[0], properties(n)"


def _ident(name: Any, what: str) -> str:
    if not isinstance(name, str) or not _IDENT.match(name):
        raise StoreError(f"invalid {what}: {name!r} (letters, digits and underscores only)")
    return name


def _is_native(value: Any) -> bool:
    if isinstance(value, str):
        return not value.startswith(_TAG)
    if isinstance(value, _SCALARS):
        return True
    if isinstance(value, list | tuple):
        # bool is an int in Python but not in FalkorDB, hence the exact type check
        kinds = {type(item) for item in value}
        return (
            len(kinds) <= 1
            and all(_is_native(item) for item in value)
            and not (kinds & {list, tuple})
        )
    return False


def encode_value(value: Any) -> Any:
    if _is_native(value):
        return list(value) if isinstance(value, tuple) else value
    try:
        return _TAG + json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise StoreError(f"property value is not JSON-serialisable: {value!r}") from exc


def decode_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_TAG):
        return json.loads(value[len(_TAG) :])
    return value


def encode_props(props: dict[str, Any]) -> dict[str, Any]:
    return {_ident(k, "property name"): encode_value(v) for k, v in props.items()}


def decode_props(props: dict[str, Any] | None) -> dict[str, Any]:
    return {k: decode_value(v) for k, v in (props or {}).items()}


def _plain(value: Any) -> Any:
    """Convert a raw query result value (client Node/Edge/Path objects
    included) into plain JSON-friendly data."""
    if hasattr(value, "labels") and hasattr(value, "properties"):
        props = decode_props(value.properties)
        labels = list(value.labels or [])
        return {
            "id": props.get("id"),
            "label": labels[0] if labels else None,
            "labels": labels,
            "props": props,
        }
    if hasattr(value, "relation") and hasattr(value, "properties"):
        return {"type": value.relation, "props": decode_props(value.properties)}
    if hasattr(value, "nodes") and hasattr(value, "edges") and callable(value.nodes):
        return {
            "nodes": [_plain(n) for n in value.nodes()],
            "edges": [_plain(e) for e in value.edges()],
        }
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return decode_value(value)


def _column_name(column: Any) -> str:
    name = column[1] if isinstance(column, list | tuple) and len(column) > 1 else column
    return name.decode() if isinstance(name, bytes) else str(name)


class FalkorStore:
    def __init__(self, client: Any) -> None:
        """`client` is a falkordb.FalkorDB (or anything with the same
        select_graph / list_graphs surface)."""
        self._client = client
        self._indexed: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings) -> FalkorStore:
        from falkordb import FalkorDB

        return cls(
            FalkorDB(
                host=settings.falkordb_host,
                port=settings.falkordb_port,
                username=settings.falkordb_username,
                password=settings.falkordb_password,
            )
        )

    # --- plumbing ------------------------------------------------------------
    def _graph_exists(self, graph: str) -> bool:
        try:
            names = self._client.list_graphs()
        except Exception as exc:
            raise StoreError(f"cannot list graphs: {exc}") from exc
        return graph in {n.decode() if isinstance(n, bytes) else n for n in names}

    def _read(self, graph: str, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Read-only query; a graph that does not exist yet yields no rows."""
        try:
            return self._client.select_graph(graph).ro_query(cypher, params or {})
        except Exception as exc:
            if not self._graph_exists(graph):
                return None
            raise StoreError(f"query failed: {exc}") from exc

    def _write(self, graph: str, cypher: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return self._client.select_graph(graph).query(cypher, params or {})
        except Exception as exc:
            raise StoreError(f"query failed: {exc}") from exc

    @staticmethod
    def _rows(result: Any) -> list[Any]:
        return list(getattr(result, "result_set", None) or []) if result is not None else []

    @staticmethod
    def _node(row: Any, at: int = 0) -> Node:
        props = decode_props(row[at + 1])
        return Node(str(props.get("id")), row[at], props)

    def _ensure_index(self, graph: str, label: str) -> None:
        with self._lock:
            if (graph, label) in self._indexed:
                return
            self._indexed.add((graph, label))
        try:
            self._client.select_graph(graph).query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
        except Exception:
            pass  # already indexed, or the server cannot index; lookups still work

    # --- nodes ---------------------------------------------------------------
    def create_node(self, graph: str, label: str, props: dict[str, Any]) -> Node:
        _ident(label, "label")
        node_id = str(props.get("id") or uuid.uuid4().hex)
        encoded = encode_props({**props, "id": node_id})
        if self._rows(
            self._read(graph, "MATCH (n {id: $id}) RETURN n.id LIMIT 1", {"id": node_id})
        ):
            raise StoreError(f"node {node_id!r} already exists in graph {graph!r}")
        self._ensure_index(graph, label)
        rows = self._rows(
            self._write(
                graph,
                f"CREATE (n:{label}) SET n = $props RETURN {_NODE_COLUMNS}",
                {"props": encoded},
            )
        )
        return self._node(rows[0])

    def get_node(self, graph: str, node_id: str, label: str | None = None) -> Node | None:
        pattern = f"(n:{_ident(label, 'label')} {{id: $id}})" if label else "(n {id: $id})"
        rows = self._rows(
            self._read(graph, f"MATCH {pattern} RETURN {_NODE_COLUMNS} LIMIT 1", {"id": node_id})
        )
        return self._node(rows[0]) if rows else None

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
        params: dict[str, Any] = {}
        clauses: list[str] = []
        for i, (key, value) in enumerate((where or {}).items()):
            _ident(key, "property name")
            if value is None:
                params[f"w{i}"] = _NULL
                clauses.append(f"(n.{key} IS NULL OR n.{key} = $w{i})")
            else:
                params[f"w{i}"] = encode_value(value)
                clauses.append(f"n.{key} = $w{i}")
        for i, (key, value) in enumerate((contains or {}).items()):
            _ident(key, "property name")
            params[f"c{i}"] = str(value).lower()
            params["tag"] = _TAG
            # String functions reject numbers and arrays, so non-strings are first
            # mapped to the tag, which the STARTS WITH check then excludes.
            text = f"(CASE WHEN typeOf(n.{key}) = 'String' THEN n.{key} ELSE $tag END)"
            clauses.append(f"(NOT {text} STARTS WITH $tag AND toLower({text}) CONTAINS $c{i})")

        cypher = f"MATCH (n:{_ident(label, 'label')})" if label else "MATCH (n)"
        if clauses:
            cypher += " WHERE " + " AND ".join(clauses)
        cypher += f" RETURN {_NODE_COLUMNS}"
        if order_by:
            _ident(order_by, "property name")
            params["null"] = _NULL
            cypher += (
                f" ORDER BY (n.{order_by} IS NULL OR n.{order_by} = $null) ASC,"
                f" n.{order_by} {'DESC' if desc else 'ASC'}, ID(n) ASC"
            )
        else:
            cypher += " ORDER BY ID(n) ASC"
        if skip:
            params["skip"] = int(skip)
            cypher += " SKIP $skip"
        if limit is not None:
            params["limit"] = int(limit)
            cypher += " LIMIT $limit"
        return [self._node(row) for row in self._rows(self._read(graph, cypher, params))]

    def update_node(self, graph: str, node_id: str, props: dict[str, Any]) -> Node:
        changes = encode_props({k: v for k, v in props.items() if k != "id"})
        if changes:
            rows = self._rows(
                self._write(
                    graph,
                    f"MATCH (n {{id: $id}}) SET n += $props RETURN {_NODE_COLUMNS}",
                    {"id": node_id, "props": changes},
                )
            )
            node = self._node(rows[0]) if rows else None
        else:
            node = self.get_node(graph, node_id)
        if node is None:
            raise NotFound(f"node {node_id!r} not found in graph {graph!r}")
        return node

    def delete_node(self, graph: str, node_id: str) -> bool:
        if self.get_node(graph, node_id) is None:  # also avoids creating an empty graph
            return False
        # FalkorDB removes a deleted node's edges with it
        result = self._write(graph, "MATCH (n {id: $id}) DELETE n", {"id": node_id})
        return int(getattr(result, "nodes_deleted", 0) or 0) > 0

    def upsert_node(
        self, graph: str, label: str, key: dict[str, Any], props: dict[str, Any]
    ) -> Node:
        _ident(label, "label")
        if not key:
            raise StoreError("upsert_node needs a non-empty key")
        params: dict[str, Any] = {}
        parts = []
        for i, (name, value) in enumerate(key.items()):
            _ident(name, "property name")
            if value is None or not _is_native(value):
                raise StoreError(f"upsert key {name!r} must be a scalar or list of scalars")
            params[f"k{i}"] = encode_value(value)
            parts.append(f"{name}: $k{i}")
        changes = encode_props({k: v for k, v in props.items() if k != "id" and k not in key})
        params["new_id"] = str(props.get("id") or uuid.uuid4().hex)
        params["props"] = changes
        self._ensure_index(graph, label)
        rows = self._rows(
            self._write(
                graph,
                f"MERGE (n:{label} {{{', '.join(parts)}}}) "
                f"ON CREATE SET n.id = $new_id "
                f"SET n += $props RETURN {_NODE_COLUMNS}",
                params,
            )
        )
        return self._node(rows[0])

    # --- edges ---------------------------------------------------------------
    def create_edge(
        self, graph: str, src: str, type: str, dst: str, props: dict[str, Any] | None = None
    ) -> Edge:
        _ident(type, "edge type")
        encoded = encode_props(props or {})
        for node_id in (src, dst):  # checked first so a missing graph is not created
            if self.get_node(graph, node_id) is None:
                raise NotFound(f"node {node_id!r} not found in graph {graph!r}")
        rows = self._rows(
            self._write(
                graph,
                f"MATCH (a {{id: $src}}), (b {{id: $dst}}) MERGE (a)-[r:{type}]->(b) "
                f"SET r += $props RETURN properties(r)",
                {"src": src, "dst": dst, "props": encoded},
            )
        )
        if not rows:
            raise NotFound(f"node {src!r} or {dst!r} not found in graph {graph!r}")
        return Edge(src, type, dst, decode_props(rows[0][0]))

    def delete_edge(self, graph: str, src: str, type: str, dst: str) -> bool:
        _ident(type, "edge type")
        params = {"src": src, "dst": dst}
        match = f"MATCH (a {{id: $src}})-[r:{type}]->(b {{id: $dst}})"
        if not self._rows(self._read(graph, f"{match} RETURN a.id LIMIT 1", params)):
            return False
        result = self._write(graph, f"{match} DELETE r", params)
        return int(getattr(result, "relationships_deleted", 0) or 0) > 0

    def edges(
        self,
        graph: str,
        node_id: str | None = None,
        type: str | None = None,
        direction: Direction = "both",
        limit: int | None = None,
    ) -> list[Edge]:
        rel = f"[r:{_ident(type, 'edge type')}]" if type else "[r]"
        tail = " RETURN a.id, type(r), b.id, properties(r) ORDER BY ID(r) ASC"
        params: dict[str, Any] = {}
        if limit is not None:
            params["limit"] = int(limit)
            tail += " LIMIT $limit"

        if node_id is None:
            queries = [f"MATCH (a)-{rel}->(b)"]
        else:
            params["id"] = node_id
            queries = []
            if direction in ("out", "both"):
                queries.append(f"MATCH (a {{id: $id}})-{rel}->(b)")
            if direction in ("in", "both"):
                queries.append(f"MATCH (a)-{rel}->(b {{id: $id}})")

        found: dict[tuple[str, str, str], Edge] = {}  # a self-loop matches both directions
        for match in queries:
            for src, edge_type, dst, props in self._rows(self._read(graph, match + tail, params)):
                found.setdefault(
                    (src, edge_type, dst), Edge(src, edge_type, dst, decode_props(props))
                )
        out = list(found.values())
        return out if limit is None else out[:limit]

    def neighbors(
        self,
        graph: str,
        node_id: str,
        type: str | None = None,
        direction: Direction = "both",
        label: str | None = None,
    ) -> list[Node]:
        order: list[str] = []
        for edge in self.edges(graph, node_id, type, direction):
            for other in {edge.src, edge.dst} - {node_id} or {node_id}:
                if other not in order:
                    order.append(other)
        if not order:
            return []
        match = f"MATCH (n:{_ident(label, 'label')})" if label else "MATCH (n)"
        rows = self._rows(
            self._read(graph, f"{match} WHERE n.id IN $ids RETURN {_NODE_COLUMNS}", {"ids": order})
        )
        by_id = {node.id: node for node in map(self._node, rows)}
        return [by_id[i] for i in order if i in by_id]

    # --- misc ----------------------------------------------------------------
    def count_by_label(self, graph: str) -> dict[str, int]:
        rows = self._rows(self._read(graph, "MATCH (n) RETURN labels(n)[0], count(n)"))
        return {label: int(count) for label, count in rows}

    def query(
        self,
        graph: str,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        readonly: bool = True,
    ) -> list[dict[str, Any]]:
        if readonly:
            # GRAPH.RO_QUERY: the server itself rejects anything that writes
            result = self._read(graph, cypher, params)
        else:
            result = self._write(graph, cypher, params)
        if result is None:
            return []
        columns = [_column_name(c) for c in getattr(result, "header", None) or []]
        out = []
        for row in self._rows(result):
            names = columns if len(columns) == len(row) else [f"col{i}" for i in range(len(row))]
            out.append({name: _plain(value) for name, value in zip(names, row, strict=True)})
        return out

    def delete_graph(self, graph: str) -> None:
        with self._lock:
            self._indexed = {pair for pair in self._indexed if pair[0] != graph}
        if not self._graph_exists(graph):
            return
        try:
            self._client.select_graph(graph).delete()
        except Exception as exc:
            if self._graph_exists(graph):
                raise StoreError(f"cannot delete graph {graph!r}: {exc}") from exc
