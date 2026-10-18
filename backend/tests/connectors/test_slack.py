import json

import httpx
import pytest

from anexa.connectors.base import ConnectorError
from anexa.connectors.slack import SlackConnector
from anexa.graph.ontology import EDGE_TYPES, NODE_LABELS

API = "https://slack.com/api"
TOKEN = "xoxb-test-token"
slack = SlackConnector()


@pytest.fixture
def ctx(make_ctx):
    return make_ctx(secrets={"bot_token": TOKEN})


def user(id, email=None, **extra):
    profile = {"real_name": f"Name {id}", "title": "Engineer"}
    if email:
        profile["email"] = email
    return {"id": id, "name": id.lower(), "real_name": f"Name {id}", "tz": "Europe/Berlin",
            "profile": profile, **extra}


def test_spec_is_complete():
    spec = slack.spec
    assert spec.key == "slack"
    secret = [f for f in spec.config_fields if f.secret]
    assert [f.name for f in secret] == ["bot_token"] and secret[0].required
    ops = {op.name: op.kind for op in spec.operations}
    assert ops == {
        "post_message": "action",
        "list_channels": "action",
        "list_users": "action",
        "channel_history": "action",
        "sync_users": "sync",
        "sync_channels": "sync",
        "sync_messages": "sync",
    }


def test_post_message_sends_json_with_bearer_token(ctx, respx_mock):
    route = respx_mock.post(f"{API}/chat.postMessage").respond(
        json={"ok": True, "channel": "C1", "ts": "171.001"}
    )
    result = slack.execute(
        "post_message", {"channel": "#eng", "text": "hello", "thread_ts": "170.5"}, ctx
    )

    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["content-type"].startswith("application/json")
    assert json.loads(request.content) == {"channel": "#eng", "text": "hello", "thread_ts": "170.5"}
    assert result.output == {"channel": "C1", "ts": "171.001"}
    assert result.graph is None


def test_post_message_omits_thread_when_not_given(ctx, respx_mock):
    route = respx_mock.post(f"{API}/chat.postMessage").respond(json={"ok": True})
    slack.execute("post_message", {"channel": "C1", "text": "hi"}, ctx)
    assert json.loads(route.calls.last.request.content) == {"channel": "C1", "text": "hi"}


def test_provider_error_is_reported_without_the_token(ctx, respx_mock):
    respx_mock.post(f"{API}/chat.postMessage").respond(
        json={"ok": False, "error": "missing_scope", "needed": "chat:write"}
    )
    with pytest.raises(ConnectorError) as exc:
        slack.execute("post_message", {"channel": "C1", "text": "hi"}, ctx)
    message = str(exc.value)
    assert "missing_scope" in message and "chat:write" in message
    assert TOKEN not in message


def test_http_error_is_a_connector_error(ctx, respx_mock):
    respx_mock.get(f"{API}/auth.test").respond(status_code=503, text="upstream down")
    with pytest.raises(ConnectorError, match="503.*upstream down"):
        slack.test(ctx)


def test_transport_failure_is_a_connector_error(ctx, respx_mock):
    respx_mock.get(f"{API}/auth.test").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(ConnectorError, match="ConnectError"):
        slack.test(ctx)


def test_missing_required_param_makes_no_request(ctx, respx_mock):
    with pytest.raises(ConnectorError, match="text"):
        slack.execute("post_message", {"channel": "C1"}, ctx)
    assert not respx_mock.calls


def test_unknown_operation(ctx):
    with pytest.raises(ConnectorError, match="no operation 'nope'"):
        slack.execute("nope", {}, ctx)


def test_missing_token(make_ctx, respx_mock):
    with pytest.raises(ConnectorError, match="bot_token"):
        slack.test(make_ctx())
    assert not respx_mock.calls


def test_test_returns_identity(ctx, respx_mock):
    route = respx_mock.get(f"{API}/auth.test").respond(
        json={"ok": True, "team": "Acme", "team_id": "T1", "user": "bot", "user_id": "U0",
              "url": "https://acme.slack.com/"}
    )
    assert slack.test(ctx) == {
        "team": "Acme", "team_id": "T1", "user": "bot", "user_id": "U0",
        "url": "https://acme.slack.com/",
    }
    assert route.calls.last.request.headers["authorization"] == f"Bearer {TOKEN}"


def test_invalid_auth(ctx, respx_mock):
    respx_mock.get(f"{API}/auth.test").respond(json={"ok": False, "error": "invalid_auth"})
    with pytest.raises(ConnectorError, match="invalid_auth"):
        slack.test(ctx)


def test_list_channels_follows_cursor(ctx, respx_mock):
    route = respx_mock.get(f"{API}/conversations.list").mock(
        side_effect=[
            httpx.Response(200, json={
                "ok": True,
                "channels": [{"id": "C1", "name": "eng", "num_members": 4,
                              "topic": {"value": "shipping"}, "purpose": {"value": ""}}],
                "response_metadata": {"next_cursor": "page2"},
            }),
            httpx.Response(200, json={
                "ok": True,
                "channels": [{"id": "C2", "name": "ops", "is_private": False}],
                "response_metadata": {"next_cursor": ""},
            }),
        ]
    )
    result = slack.execute("list_channels", {}, ctx)

    assert route.call_count == 2
    first, second = (call.request.url.params for call in route.calls)
    assert first["types"] == "public_channel" and first["exclude_archived"] == "true"
    assert "cursor" not in first and second["cursor"] == "page2"
    assert result.output["count"] == 2
    assert result.output["channels"][0] == {
        "id": "C1", "name": "eng", "is_private": False, "num_members": 4,
        "topic": "shipping", "purpose": None,
    }


def test_list_channels_can_include_private(ctx, respx_mock):
    route = respx_mock.get(f"{API}/conversations.list").respond(json={"ok": True, "channels": []})
    slack.execute("list_channels", {"include_private": "true"}, ctx)
    assert route.calls.last.request.url.params["types"] == "public_channel,private_channel"


def test_list_users_skips_bots_and_deleted(ctx, respx_mock):
    respx_mock.get(f"{API}/users.list").respond(json={
        "ok": True,
        "members": [
            user("U1", "Ada@Acme.com"),
            user("U2", deleted=True),
            user("B1", is_bot=True),
            user("USLACKBOT"),
        ],
    })
    result = slack.execute("list_users", {}, ctx)
    assert result.output["count"] == 1
    assert result.output["users"][0] == {
        "id": "U1", "name": "Name U1", "handle": "u1", "email": "Ada@Acme.com",
        "title": "Engineer", "timezone": "Europe/Berlin", "is_admin": False,
    }


def test_channel_history(ctx, respx_mock):
    route = respx_mock.get(f"{API}/conversations.history").respond(json={
        "ok": True,
        "messages": [{"ts": "2.0", "user": "U1", "text": "second"},
                     {"ts": "1.0", "user": "U2", "text": "first", "thread_ts": "1.0"}],
    })
    result = slack.execute("channel_history", {"channel": "C1", "limit": "2"}, ctx)

    params = route.calls.last.request.url.params
    assert params["channel"] == "C1" and params["limit"] == "2"
    assert result.output["count"] == 2
    assert result.output["messages"][1] == {
        "ts": "1.0", "user": "U2", "text": "first", "thread_ts": "1.0",
    }


def test_sync_users_keys_people_by_email(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/auth.test").respond(json={"ok": True, "url": "https://acme.slack.com/"})
    respx_mock.get(f"{API}/users.list").respond(json={
        "ok": True,
        "members": [user("U1", "Ada@Acme.com"), user("U2"), user("B1", is_bot=True)],
    })
    result = slack.execute("sync_users", {}, ctx)

    delta = delta_of(result.graph)
    assert delta.keys("Person") == ["email:ada@acme.com", "slack:user:U2"]
    ada = delta.node("Person", "email:ada@acme.com")
    assert ada.props["name"] == "Name U1"
    assert ada.props["email"] == "Ada@Acme.com"
    assert ada.props["slack_id"] == "U1"
    assert ada.props["url"] == "https://acme.slack.com/team/U1"
    assert result.output == {"people": 2}
    assert all(n.label in NODE_LABELS for n in result.graph.nodes)


def test_sync_channels_links_members_to_teams(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/auth.test").respond(json={"ok": True, "url": "https://acme.slack.com"})
    respx_mock.get(f"{API}/users.list").respond(json={
        "ok": True, "members": [user("U1", "ada@acme.com"), user("U2"), user("U3", "c@acme.com")],
    })
    respx_mock.get(f"{API}/conversations.list").respond(json={
        "ok": True,
        "channels": [{"id": "C1", "name": "eng", "num_members": 3,
                      "purpose": {"value": "Engineering"}},
                     {"id": "C2", "name": "ops"}],
    })
    members = respx_mock.get(f"{API}/conversations.members").mock(
        side_effect=lambda request: httpx.Response(200, json={
            "ok": True,
            # B9 is a bot: not in the people list, so it gets no node and no edge.
            "members": {"C1": ["U1", "U2", "B9"], "C2": ["U1"]}[request.url.params["channel"]],
        })
    )
    result = slack.execute("sync_channels", {}, ctx)

    delta = delta_of(result.graph)
    assert members.call_count == 2
    assert delta.keys("Team") == ["slack:channel:C1", "slack:channel:C2"]
    eng = delta.node("Team", "slack:channel:C1")
    assert eng.props["name"] == "#eng"
    assert eng.props["purpose"] == "Engineering"
    assert eng.props["url"] == "https://acme.slack.com/archives/C1"
    # U3 is in no channel, so it is not part of this delta.
    assert delta.keys("Person") == ["email:ada@acme.com", "slack:user:U2"]
    assert delta.edges() == [
        ("Person", "email:ada@acme.com", "MEMBER_OF", "Team", "slack:channel:C1"),
        ("Person", "email:ada@acme.com", "MEMBER_OF", "Team", "slack:channel:C2"),
        ("Person", "slack:user:U2", "MEMBER_OF", "Team", "slack:channel:C1"),
    ]
    assert all(e.type in EDGE_TYPES for e in result.graph.edges)
    assert result.output == {"teams": 2, "people": 2, "memberships": 3}


def test_sync_channels_respects_caps(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/auth.test").respond(json={"ok": True, "url": ""})
    respx_mock.get(f"{API}/users.list").respond(json={
        "ok": True, "members": [user("U1"), user("U2"), user("U3")],
    })
    respx_mock.get(f"{API}/conversations.list").respond(json={
        "ok": True, "channels": [{"id": "C1", "name": "a"}, {"id": "C2", "name": "b"}],
    })
    members = respx_mock.get(f"{API}/conversations.members").respond(json={
        "ok": True, "members": ["U1", "U2", "U3"],
        "response_metadata": {"next_cursor": "more"},
    })
    result = slack.execute("sync_channels", {"max_channels": 1, "max_members": 2}, ctx)

    delta = delta_of(result.graph)
    assert delta.keys("Team") == ["slack:channel:C1"]
    assert len(delta.edges("MEMBER_OF")) == 2
    assert members.call_count == 1  # cap reached, cursor not followed
    assert "url" not in {k for k, v in delta.node("Team", "slack:channel:C1").props.items() if v}


def test_sync_channels_without_members_skips_user_and_member_calls(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/auth.test").respond(json={"ok": True, "url": "https://acme.slack.com/"})
    respx_mock.get(f"{API}/conversations.list").respond(json={
        "ok": True, "channels": [{"id": "C1", "name": "eng"}],
    })
    result = slack.execute("sync_channels", {"include_members": False}, ctx)
    assert delta_of(result.graph).keys("Person") == []
    assert result.graph.edges == []


def test_sync_messages_adds_text_authors_threads_and_mentions(ctx, respx_mock, delta_of):
    respx_mock.get(f"{API}/auth.test").respond(json={"ok": True, "url": "https://acme.slack.com/"})
    respx_mock.get(f"{API}/users.list").respond(json={
        "ok": True, "members": [user("U1", "Ada@Acme.com"), user("U2")],
    })
    history = respx_mock.get(f"{API}/conversations.history").respond(json={
        "ok": True,
        "messages": [
            {"ts": "1700000100.000200", "user": "U2", "text": "agreed <@U1>",
             "thread_ts": "1700000000.000100"},
            {"ts": "1700000000.000100", "user": "U1", "text": "ship it " + "x" * 5000,
             "thread_ts": "1700000000.000100"},
            {"ts": "1700000050.000000", "bot_id": "B1", "text": "deploy done"},
        ],
    })
    result = slack.execute("sync_messages", {"channel": "C1"}, ctx)

    params = history.calls.last.request.url.params
    assert params["channel"] == "C1" and params["limit"] == "200"
    delta = delta_of(result.graph)
    first, reply = "slack:msg:C1:1700000000.000100", "slack:msg:C1:1700000100.000200"
    assert delta.keys("Message") == [first, reply]
    root = delta.node("Message", first)
    assert root.props["text"] == ("ship it " + "x" * 5000)[:4000]
    assert root.props["name"] == ("ship it " + "x" * 5000)[:80]
    assert root.props["created_at"] == "2023-11-14T22:13:20+00:00"
    assert root.props["url"] == "https://acme.slack.com/archives/C1/p1700000000000100"
    assert delta.node("Message", reply).props["text"] == "agreed <@U1>"
    assert delta.edges("AUTHORED") == [
        ("Person", "email:ada@acme.com", "AUTHORED", "Message", first),
        ("Person", "slack:user:U2", "AUTHORED", "Message", reply),
    ]
    assert delta.edges("POSTED_IN") == [
        ("Message", first, "POSTED_IN", "Team", "slack:channel:C1"),
        ("Message", reply, "POSTED_IN", "Team", "slack:channel:C1"),
    ]
    assert delta.edges("REPLY_TO") == [("Message", reply, "REPLY_TO", "Message", first)]
    assert delta.edges("MENTIONS") == [
        ("Message", reply, "MENTIONS", "Person", "email:ada@acme.com"),
    ]
    assert all(n.label in NODE_LABELS for n in result.graph.nodes)
    assert all(e.type in EDGE_TYPES for e in result.graph.edges)
    assert result.output == {"channel": "C1", "messages": 2}


def test_sync_messages_requires_channel(ctx, respx_mock):
    with pytest.raises(ConnectorError, match="channel"):
        slack.execute("sync_messages", {}, ctx)
    assert not respx_mock.calls
