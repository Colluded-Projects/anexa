from __future__ import annotations

from typing import Any

from ..graph.ontology import entity_key, person_key
from . import register
from ._http import as_bool, as_int, json_body, require, send
from .base import (
    Connector,
    ConnectorContext,
    ConnectorError,
    ConnectorSpec,
    EdgeUpsert,
    FieldSpec,
    GraphDelta,
    NodeUpsert,
    OperationResult,
    OperationSpec,
)

API = "https://slack.com/api"
PAGE_SIZE = 200
MAX_PAGES = 25


class SlackConnector(Connector):
    spec = ConnectorSpec(
        key="slack",
        title="Slack",
        description="Post messages and read channels and people from a Slack workspace.",
        config_fields=[
            FieldSpec(
                name="bot_token",
                label="Bot token",
                required=True,
                secret=True,
                placeholder="xoxb-...",
                help="Bot User OAuth Token of a Slack app installed in the workspace. Scopes: "
                "chat:write, channels:read, channels:history, users:read, users:read.email.",
            ),
        ],
        operations=[
            OperationSpec(
                name="post_message",
                title="Post message",
                description="Send a message to a channel or thread.",
                params=[
                    FieldSpec(
                        name="channel",
                        label="Channel",
                        required=True,
                        placeholder="#general or C0123456789",
                    ),
                    FieldSpec(name="text", label="Text", type="text", required=True),
                    FieldSpec(
                        name="thread_ts",
                        label="Thread timestamp",
                        help="Reply inside this thread instead of posting to the channel.",
                    ),
                ],
            ),
            OperationSpec(
                name="list_channels",
                title="List channels",
                description="List the workspace's channels.",
                params=[
                    FieldSpec(
                        name="include_private",
                        label="Include private channels",
                        type="boolean",
                        default=False,
                        help="Needs the groups:read scope.",
                    ),
                ],
            ),
            OperationSpec(
                name="list_users", title="List users", description="List active human members."
            ),
            OperationSpec(
                name="channel_history",
                title="Channel history",
                description="Fetch the most recent messages of a channel.",
                params=[
                    FieldSpec(
                        name="channel", label="Channel ID", required=True, placeholder="C0123456789"
                    ),
                    FieldSpec(name="limit", label="Limit", type="number", default=50),
                ],
            ),
            OperationSpec(
                name="sync_users",
                title="Sync people",
                kind="sync",
                description="Add every active Slack member to the company graph as a Person.",
            ),
            OperationSpec(
                name="sync_channels",
                title="Sync channels",
                kind="sync",
                description="Add each channel as a Team, with its members.",
                params=[
                    FieldSpec(
                        name="include_members",
                        label="Include members",
                        type="boolean",
                        default=True,
                    ),
                    FieldSpec(
                        name="max_channels",
                        label="Max channels",
                        type="number",
                        default=100,
                        help="Membership is fetched one channel at a time.",
                    ),
                    FieldSpec(
                        name="max_members",
                        label="Max members per channel",
                        type="number",
                        default=500,
                    ),
                ],
            ),
        ],
    )

    # --- transport -----------------------------------------------------------
    def _call(
        self,
        ctx: ConnectorContext,
        method: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = require(ctx.secrets, "bot_token", "slack")
        headers = {"Authorization": f"Bearer {token}"}
        if json is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            resp = send(ctx, "slack", "POST", f"{API}/{method}", headers=headers, json=json)
        else:
            resp = send(ctx, "slack", "GET", f"{API}/{method}", headers=headers, params=params)
        body = json_body(resp, "slack")
        if not body.get("ok"):
            detail = body.get("error", "unknown_error")
            if body.get("needed"):
                detail += f" (needs scope {body['needed']})"
            raise ConnectorError(f"slack: {method} failed: {detail}")
        return body

    def _paginate(
        self,
        ctx: ConnectorContext,
        method: str,
        field: str,
        params: dict[str, Any] | None = None,
        cap: int | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        query = {"limit": PAGE_SIZE, **(params or {})}
        for _ in range(MAX_PAGES):
            body = self._call(ctx, method, params=query)
            items.extend(body.get(field) or [])
            cursor = (body.get("response_metadata") or {}).get("next_cursor")
            if not cursor or (cap is not None and len(items) >= cap):
                break
            query = {**query, "cursor": cursor}
        return items if cap is None else items[:cap]

    def _humans(self, ctx: ConnectorContext) -> list[dict[str, Any]]:
        return [
            u
            for u in self._paginate(ctx, "users.list", "members")
            if not u.get("deleted") and not u.get("is_bot") and u.get("id") != "USLACKBOT"
        ]

    def _channels(self, ctx: ConnectorContext, include_private: bool) -> list[dict[str, Any]]:
        types = "public_channel,private_channel" if include_private else "public_channel"
        return self._paginate(
            ctx, "conversations.list", "channels", {"types": types, "exclude_archived": "true"}
        )

    # --- shaping -------------------------------------------------------------
    @staticmethod
    def _user(user: dict[str, Any]) -> dict[str, Any]:
        profile = user.get("profile") or {}
        return {
            "id": user.get("id"),
            "name": user.get("real_name") or profile.get("real_name") or user.get("name"),
            "handle": user.get("name"),
            "email": profile.get("email"),
            "title": profile.get("title") or None,
            "timezone": user.get("tz"),
            "is_admin": bool(user.get("is_admin")),
        }

    @staticmethod
    def _channel(channel: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": channel.get("id"),
            "name": channel.get("name"),
            "is_private": bool(channel.get("is_private")),
            "num_members": channel.get("num_members"),
            "topic": (channel.get("topic") or {}).get("value") or None,
            "purpose": (channel.get("purpose") or {}).get("value") or None,
        }

    def _person_node(self, user: dict[str, Any], workspace_url: str) -> NodeUpsert:
        info = self._user(user)
        return NodeUpsert(
            label="Person",
            key=person_key(info["email"], "slack", info["id"]),
            props={
                "name": info["name"],
                "email": info["email"],
                "title": info["title"],
                "timezone": info["timezone"],
                "slack_id": info["id"],
                "slack_handle": info["handle"],
                "url": f"{workspace_url}team/{info['id']}" if workspace_url else None,
            },
        )

    def _workspace_url(self, ctx: ConnectorContext) -> str:
        url = self._call(ctx, "auth.test").get("url") or ""
        return url if not url or url.endswith("/") else url + "/"

    # --- operations ----------------------------------------------------------
    def execute(
        self, operation: str, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        self.validate_params(operation, params)
        return getattr(self, f"_op_{operation}")(params, ctx)

    def test(self, ctx: ConnectorContext) -> dict[str, Any]:
        body = self._call(ctx, "auth.test")
        return {key: body.get(key) for key in ("team", "team_id", "user", "user_id", "url")}

    def _op_post_message(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        payload = {"channel": params["channel"], "text": params["text"]}
        if params.get("thread_ts"):
            payload["thread_ts"] = str(params["thread_ts"])
        body = self._call(ctx, "chat.postMessage", json=payload)
        return OperationResult(output={"channel": body.get("channel"), "ts": body.get("ts")})

    def _op_list_channels(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        channels = self._channels(ctx, as_bool(params.get("include_private"), False))
        out = [self._channel(c) for c in channels]
        return OperationResult(output={"channels": out, "count": len(out)})

    def _op_list_users(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        out = [self._user(u) for u in self._humans(ctx)]
        return OperationResult(output={"users": out, "count": len(out)})

    def _op_channel_history(
        self, params: dict[str, Any], ctx: ConnectorContext
    ) -> OperationResult:
        limit = as_int(params.get("limit"), 50, 1, 1000)
        body = self._call(
            ctx, "conversations.history", params={"channel": params["channel"], "limit": limit}
        )
        messages = [
            {
                "ts": m.get("ts"),
                "user": m.get("user"),
                "text": m.get("text", ""),
                "thread_ts": m.get("thread_ts"),
            }
            for m in body.get("messages") or []
        ]
        return OperationResult(
            output={"channel": params["channel"], "messages": messages, "count": len(messages)}
        )

    def _op_sync_users(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        workspace_url = self._workspace_url(ctx)
        nodes = [self._person_node(u, workspace_url) for u in self._humans(ctx)]
        return OperationResult(output={"people": len(nodes)}, graph=GraphDelta(nodes=nodes))

    def _op_sync_channels(self, params: dict[str, Any], ctx: ConnectorContext) -> OperationResult:
        include_members = as_bool(params.get("include_members"), True)
        max_channels = as_int(params.get("max_channels"), 100, 1, 1000)
        max_members = as_int(params.get("max_members"), 500, 1, 5000)

        workspace_url = self._workspace_url(ctx)
        channels = self._channels(ctx, include_private=False)[:max_channels]
        people = {u["id"]: self._person_node(u, workspace_url) for u in self._humans(ctx)} if (
            include_members
        ) else {}

        delta = GraphDelta()
        used: dict[str, NodeUpsert] = {}
        for channel in channels:
            info = self._channel(channel)
            team_key = entity_key("slack", "channel", info["id"])
            delta.nodes.append(
                NodeUpsert(
                    label="Team",
                    key=team_key,
                    props={
                        "name": f"#{info['name']}",
                        "kind": "slack_channel",
                        "slack_id": info["id"],
                        "topic": info["topic"],
                        "purpose": info["purpose"],
                        "num_members": info["num_members"],
                        "is_private": info["is_private"],
                        "url": f"{workspace_url}archives/{info['id']}" if workspace_url else None,
                    },
                )
            )
            if not include_members:
                continue
            member_ids = self._paginate(
                ctx, "conversations.members", "members", {"channel": info["id"]}, cap=max_members
            )
            for member_id in member_ids:
                person = people.get(member_id)  # bots and deactivated users are not people
                if person is None:
                    continue
                used[member_id] = person
                delta.edges.append(
                    EdgeUpsert(
                        src_label="Person",
                        src_key=person.key,
                        type="MEMBER_OF",
                        dst_label="Team",
                        dst_key=team_key,
                    )
                )
        delta.nodes.extend(used.values())
        return OperationResult(
            output={"teams": len(channels), "people": len(used), "memberships": len(delta.edges)},
            graph=delta,
        )


register(SlackConnector())
