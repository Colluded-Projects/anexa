from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from ...graph.ontology import EDGE_TYPES, NODE_LABELS
from ...models import new_id, utcnow
from ...store import Edge, Node, StoreError
from ..common import invalid
from ..deps import WorkspaceCtx, WorkspaceDep
from ..schemas import (
    GraphEdgeIn,
    GraphEdgeOut,
    GraphNodeDetail,
    GraphNodeIn,
    GraphNodeOut,
    GraphNodePatch,
    GraphQueryIn,
    GraphQueryOut,
    GraphStatsOut,
    SubgraphOut,
)

router = APIRouter(prefix="/api/workspaces/{ws}/graph", tags=["graph"])

# Properties surfaced as GraphNode fields; everything else is reported under `props`.
_NAMED = {"id", "label", "name", "key", "source", "url", "updated_at"}
# Named properties a client may not set through `props`.
_RESERVED = _NAMED - {"url"}


def _node_out(node: Node) -> GraphNodeOut:
    p = node.props
    url = p.get("url")
    return GraphNodeOut(
        id=node.id,
        label=node.label,
        name=str(p.get("name") or ""),
        key=str(p.get("key") or ""),
        source=str(p.get("source") or ""),
        url=str(url) if url else None,
        props={k: v for k, v in p.items() if k not in _NAMED and v is not None},
        updated_at=p.get("updated_at"),
    )


def _edge_out(edge: Edge) -> GraphEdgeOut:
    return GraphEdgeOut(src=edge.src, type=edge.type, dst=edge.dst, props=edge.props)


def _check_label(label: str) -> None:
    if label not in NODE_LABELS:
        raise invalid(f"unknown node label {label!r} (expected one of: {', '.join(NODE_LABELS)})")


def _node(ctx: WorkspaceCtx, node_id: str) -> Node:
    node = ctx.repos.store.get_node(ctx.graph, node_id)
    if node is None:
        raise HTTPException(404, "node not found")
    return node


@router.get("/ontology")
def ontology(ctx: WorkspaceDep) -> dict[str, dict[str, str]]:
    return {"node_labels": NODE_LABELS, "edge_types": EDGE_TYPES}


@router.get("/stats")
def stats(ctx: WorkspaceDep) -> GraphStatsOut:
    counts = ctx.repos.store.count_by_label(ctx.graph)
    return GraphStatsOut(
        nodes=counts,
        total_nodes=sum(counts.values()),
        total_edges=len(ctx.repos.store.edges(ctx.graph)),
    )


@router.get("/nodes")
def list_nodes(
    ctx: WorkspaceDep,
    label: str | None = None,
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[GraphNodeOut]:
    if label:
        _check_label(label)
    nodes = ctx.repos.store.find_nodes(
        ctx.graph,
        label or None,
        contains={"name": q} if q else None,
        order_by="name",
        limit=limit,
    )
    return [_node_out(n) for n in nodes]


@router.post("/nodes", status_code=201)
def create_node(body: GraphNodeIn, ctx: WorkspaceDep) -> GraphNodeOut:
    _check_label(body.label)
    store = ctx.repos.store
    node_id = new_id()
    key = (body.key or "").strip() or f"manual:{node_id}"
    if store.find_nodes(ctx.graph, body.label, {"key": key}, limit=1):
        raise HTTPException(409, f"a {body.label} with key {key!r} already exists")
    props = {k: v for k, v in body.props.items() if k not in _RESERVED and v is not None}
    node = store.create_node(
        ctx.graph,
        body.label,
        {
            **props,
            "id": node_id,
            "name": body.name.strip(),
            "key": key,
            "source": "manual",
            "updated_at": utcnow(),
        },
    )
    return _node_out(node)


@router.get("/nodes/{node_id}")
def get_node(node_id: str, ctx: WorkspaceDep) -> GraphNodeDetail:
    node = _node(ctx, node_id)
    store = ctx.repos.store
    return GraphNodeDetail(
        **_node_out(node).model_dump(),
        edges=[_edge_out(e) for e in store.edges(ctx.graph, node_id)],
        neighbors=[_node_out(n) for n in store.neighbors(ctx.graph, node_id)],
    )


@router.patch("/nodes/{node_id}")
def update_node(node_id: str, body: GraphNodePatch, ctx: WorkspaceDep) -> GraphNodeOut:
    _node(ctx, node_id)
    changes: dict[str, Any] = {k: v for k, v in (body.props or {}).items() if k not in _RESERVED}
    if body.name is not None:
        changes["name"] = body.name.strip()
    changes["updated_at"] = utcnow()
    return _node_out(ctx.repos.store.update_node(ctx.graph, node_id, changes))


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: str, ctx: WorkspaceDep) -> None:
    _node(ctx, node_id)
    ctx.repos.store.delete_node(ctx.graph, node_id)


@router.post("/edges", status_code=201)
def create_edge(body: GraphEdgeIn, ctx: WorkspaceDep) -> GraphEdgeOut:
    if body.type not in EDGE_TYPES:
        raise invalid(f"unknown edge type {body.type!r} (expected one of: {', '.join(EDGE_TYPES)})")
    for node_id in (body.src, body.dst):
        if ctx.repos.store.get_node(ctx.graph, node_id) is None:
            raise HTTPException(404, f"node {node_id!r} not found")
    props = {**body.props, "source": body.props.get("source", "manual")}
    return _edge_out(ctx.repos.store.create_edge(ctx.graph, body.src, body.type, body.dst, props))


@router.delete("/edges", status_code=204)
def delete_edge(ctx: WorkspaceDep, src: str, type: str, dst: str) -> None:
    if not ctx.repos.store.delete_edge(ctx.graph, src, type, dst):
        raise HTTPException(404, "edge not found")


@router.get("/subgraph")
def subgraph(
    ctx: WorkspaceDep,
    label: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> SubgraphOut:
    if label:
        _check_label(label)
    store = ctx.repos.store
    nodes = store.find_nodes(
        ctx.graph, label or None, order_by="updated_at", desc=True, limit=limit
    )
    ids = {n.id for n in nodes}
    edges = [e for e in store.edges(ctx.graph) if e.src in ids and e.dst in ids]
    return SubgraphOut(nodes=[_node_out(n) for n in nodes], edges=[_edge_out(e) for e in edges])


@router.post("/query")
def query(body: GraphQueryIn, ctx: WorkspaceDep) -> GraphQueryOut:
    try:
        rows = ctx.repos.store.query(ctx.graph, body.cypher, body.params, readonly=True)
    except NotImplementedError as exc:
        raise HTTPException(501, str(exc) or "Cypher queries need the FalkorDB backend") from exc
    except StoreError as exc:
        raise invalid(str(exc)) from exc
    except Exception as exc:  # the driver reports Cypher errors with its own exception types
        raise invalid(f"query failed: {exc}") from exc
    return GraphQueryOut(rows=rows)
