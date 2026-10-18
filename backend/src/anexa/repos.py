"""Typed persistence on top of GraphStore. All platform data lives in the
system graph; company knowledge lives in one graph per workspace (graph/)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .config import Settings, get_settings
from .models import (
    Action,
    Agent,
    ApiKey,
    Connection,
    Operator,
    Role,
    Run,
    Schedule,
    User,
    Workspace,
    utcnow,
)
from .store import GraphStore, NotFound, get_store

MEMBER_OF = "MEMBER_OF"


class Repo[T: BaseModel]:
    def __init__(self, store: GraphStore, graph: str, label: str, model: type[T]) -> None:
        self.store, self.graph, self.label, self.model = store, graph, label, model

    def create(self, obj: T) -> T:
        self.store.create_node(self.graph, self.label, obj.model_dump(mode="json"))
        return obj

    def get(self, id: str) -> T | None:
        node = self.store.get_node(self.graph, id, self.label)
        return self.model.model_validate(node.props) if node else None

    def list(
        self,
        *,
        order_by: str = "created_at",
        desc: bool = True,
        skip: int = 0,
        limit: int | None = None,
        **where: Any,
    ) -> list[T]:
        nodes = self.store.find_nodes(
            self.graph,
            self.label,
            where or None,
            order_by=order_by,
            desc=desc,
            skip=skip,
            limit=limit,
        )
        return [self.model.model_validate(n.props) for n in nodes]

    def first(self, **where: Any) -> T | None:
        found = self.list(limit=1, **where)
        return found[0] if found else None

    def update(self, id: str, **changes: Any) -> T:
        """Validate and persist `changes`; bumps updated_at. Raises NotFound."""
        current = self.get(id)
        if current is None:
            raise NotFound(f"{self.label} {id!r} not found")
        merged = self.model.model_validate(
            {**current.model_dump(mode="json"), **changes, "updated_at": utcnow()}
        )
        dumped = merged.model_dump(mode="json")
        self.store.update_node(
            self.graph, id, {k: dumped[k] for k in (*changes, "updated_at") if k != "id"}
        )
        return merged

    def delete(self, id: str) -> bool:
        if self.store.get_node(self.graph, id, self.label) is None:
            return False
        return self.store.delete_node(self.graph, id)


class Repos:
    def __init__(self, store: GraphStore | None = None, settings: Settings | None = None) -> None:
        self.store = store or get_store()
        self.settings = settings or get_settings()
        g = self.settings.system_graph
        self.graph = g
        self.users = Repo(self.store, g, "User", User)
        self.workspaces = Repo(self.store, g, "Workspace", Workspace)
        self.api_keys = Repo(self.store, g, "ApiKey", ApiKey)
        self.connections = Repo(self.store, g, "Connection", Connection)
        self.actions = Repo(self.store, g, "Action", Action)
        self.operators = Repo(self.store, g, "Operator", Operator)
        self.schedules = Repo(self.store, g, "Schedule", Schedule)
        self.runs = Repo(self.store, g, "Run", Run)
        self.agents = Repo(self.store, g, "Agent", Agent)

    # --- membership: (User)-[MEMBER_OF {role}]->(Workspace) ------------------
    def add_member(self, workspace_id: str, user_id: str, role: Role = "member") -> None:
        self.store.create_edge(self.graph, user_id, MEMBER_OF, workspace_id, {"role": role})

    def remove_member(self, workspace_id: str, user_id: str) -> bool:
        return self.store.delete_edge(self.graph, user_id, MEMBER_OF, workspace_id)

    def get_role(self, workspace_id: str, user_id: str) -> Role | None:
        for edge in self.store.edges(self.graph, user_id, MEMBER_OF, "out"):
            if edge.dst == workspace_id:
                return edge.props.get("role", "member")
        return None

    def workspaces_for(self, user_id: str) -> list[tuple[Workspace, Role]]:
        out = []
        for edge in self.store.edges(self.graph, user_id, MEMBER_OF, "out"):
            ws = self.workspaces.get(edge.dst)
            if ws:
                out.append((ws, edge.props.get("role", "member")))
        return sorted(out, key=lambda pair: pair[0].created_at)

    def members_of(self, workspace_id: str) -> list[tuple[User, Role]]:
        out = []
        for edge in self.store.edges(self.graph, workspace_id, MEMBER_OF, "in"):
            user = self.users.get(edge.src)
            if user:
                out.append((user, edge.props.get("role", "member")))
        return sorted(out, key=lambda pair: pair[0].created_at)

    def company_graph(self, workspace_id: str) -> str:
        return self.settings.company_graph(workspace_id)
