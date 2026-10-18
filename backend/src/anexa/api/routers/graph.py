from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from ...graph import demo
from ...graph.evaluate import score
from ...graph.linking import link_graph, llm
from ...graph.linking.rules import experts
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
    LinkEdgeIn,
    LinkProposalsIn,
    LinkReviewOut,
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


@router.post("/demo", status_code=201)
def load_demo(ctx: WorkspaceDep) -> dict[str, Any]:
    """Write the fake demo company into this workspace's graph."""
    return {"loaded": demo.load(ctx.repos.store, ctx.graph)}


@router.post("/link")
def link(ctx: WorkspaceDep) -> dict[str, Any]:
    """Run the linker over the whole graph."""
    return link_graph(ctx.repos.store, ctx.graph)


@router.get("/link/prompt")
def link_prompt(ctx: WorkspaceDep) -> dict[str, Any]:
    """The catalog the LLM linker reads, for a model outside the platform
    (Claude Code over MCP) to answer with POST /link/proposals."""
    nodes, prompt = llm.catalog(ctx.repos.store, ctx.graph)
    return {"prompt": prompt, "nodes": len(nodes), "schema": llm.SCHEMA}


@router.post("/link/proposals")
def link_proposals(body: LinkProposalsIn, ctx: WorkspaceDep) -> dict[str, Any]:
    """Validate proposed links with the same checks as the LLM linker and write
    the ones that pass. Unsure ones show up in the review queue."""
    nodes, _ = llm.catalog(ctx.repos.store, ctx.graph)
    written = llm.apply_answer(ctx.repos.store, ctx.graph, nodes, body.model_dump())
    return {"links": written}


@router.get("/link/score")
def link_score(ctx: WorkspaceDep) -> dict[str, dict[str, float | int]]:
    """Precision/recall of the current links against the demo company's gold links."""
    return score(ctx.repos.store, ctx.graph)


# Linker edges below this confidence wait for a human in the review queue.
REVIEW_BELOW = 0.7


@router.get("/link/review")
def link_review(ctx: WorkspaceDep) -> list[LinkReviewOut]:
    """Linker edges the linker was unsure about, least sure first."""
    store = ctx.repos.store
    name = {n.id: str(n.props.get("name") or "") for n in store.find_nodes(ctx.graph)}
    unsure = [
        e
        for e in store.edges(ctx.graph)
        if e.props.get("source") == "linker" and e.props["confidence"] < REVIEW_BELOW
    ]
    unsure.sort(key=lambda e: e.props["confidence"])
    return [
        LinkReviewOut(
            src=e.src,
            src_name=name[e.src],
            type=e.type,
            dst=e.dst,
            dst_name=name[e.dst],
            method=e.props["method"],
            confidence=e.props["confidence"],
            evidence=e.props.get("evidence"),
        )
        for e in unsure
    ]


@router.post("/link/review/accept")
def link_accept(body: LinkEdgeIn, ctx: WorkspaceDep) -> GraphEdgeOut:
    """A human confirmed this linker edge. Rejecting is DELETE /graph/edges."""
    store = ctx.repos.store
    found = [
        e for e in store.edges(ctx.graph, body.src, body.type, "out") if e.dst == body.dst
    ]
    if not found:
        raise HTTPException(404, "edge not found")
    props = {"confidence": 1.0, "method": f"{found[0].props['method']}+human"}
    return _edge_out(store.create_edge(ctx.graph, body.src, body.type, body.dst, props))


@router.get("/experts")
def list_experts(ctx: WorkspaceDep, topic: str) -> list[dict[str, Any]]:
    """People who know about a topic word, found by the linker."""
    return experts(ctx.repos.store, ctx.graph, topic)


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
