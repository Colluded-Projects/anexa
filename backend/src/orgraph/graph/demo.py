"""A small fake company, shaped exactly like the connectors' output, plus the
links a perfect linker would find in it ("gold"). Used by tests and by the
"Load demo company" button to compare linking strategies.

The people deliberately have different identities per system (hidden emails,
logins, Jira account ids), and some items are only related by what they talk
about, never by an explicit id.
"""

from __future__ import annotations

from ..connectors.base import EdgeUpsert, GraphDelta, NodeUpsert

# ---- identities -------------------------------------------------------------

ADA, BOB, CAROL, DAN = (
    "email:ada@acme.io",
    "email:bob@acme.io",
    "email:carol@acme.io",
    "email:dan@acme.io",
)
GH_ADA, GH_BOB = "github:user:ada-l", "github:user:bstone"
JIRA_ADA, JIRA_CAROL, JIRA_DAN = "jira:user:a1", "jira:user:c3", "jira:user:d4"

ENG = "slack:channel:C1"
M1, M2, M3, M4, M5 = (f"slack:msg:C1:17000000{i}.000100" for i in range(1, 6))
ENG12, ENG15, BILL3 = "jira:issue:ENG-12", "jira:issue:ENG-15", "jira:issue:BILL-3"
API7, API9 = "github:issue:acme/api#7", "github:issue:acme/api#9"
RFC1, ADR4 = "google:file:rfc1", "google:file:adr4"


def _n(label: str, key: str, **props) -> NodeUpsert:
    return NodeUpsert(label=label, key=key, props=props)


def _e(src_label: str, src: str, type: str, dst_label: str, dst: str) -> EdgeUpsert:
    return EdgeUpsert(src_label=src_label, src_key=src, type=type, dst_label=dst_label, dst_key=dst)


def _msg(key: str, text: str, ts: str) -> NodeUpsert:
    return _n("Message", key, name=text[:80], text=text, created_at=ts)


SLACK = GraphDelta(
    nodes=[
        _n("Person", ADA, name="Ada Lovelace", email="ada@acme.io", slack_handle="ada"),
        _n("Person", BOB, name="Bob Stone", email="bob@acme.io", slack_handle="bob"),
        _n("Person", CAROL, name="Carol Diaz", email="carol@acme.io", slack_handle="carol"),
        _n("Person", DAN, name="Dan Wu", email="dan@acme.io", slack_handle="dan"),
        _n("Team", ENG, name="#eng", kind="slack_channel"),
        _msg(
            M1,
            "Proposal: move the event bus to Kafka, RFC here "
            "https://docs.google.com/document/d/rfc1/edit",
            "2026-09-01T09:00:00Z",
        ),
        _msg(
            M2,
            "Decision: we go with Kafka for the event bus, tracked in ENG-12",
            "2026-09-01T10:00:00Z",
        ),
        _msg(
            M3,
            "login is getting hammered by bots, we need rate limiting on the login endpoint",
            "2026-09-03T08:00:00Z",
        ),
        _msg(
            M4,
            "invoice export to CSV is broken for EU customers again",
            "2026-09-04T14:00:00Z",
        ),
        _msg(
            M5,
            "PR for the kafka producer is up https://github.com/acme/api/pull/9",
            "2026-09-05T16:00:00Z",
        ),
    ],
    edges=[
        *(_e("Person", p, "MEMBER_OF", "Team", ENG) for p in (ADA, BOB, CAROL, DAN)),
        *(_e("Message", m, "POSTED_IN", "Team", ENG) for m in (M1, M2, M3, M4, M5)),
        _e("Person", ADA, "AUTHORED", "Message", M1),
        _e("Person", BOB, "AUTHORED", "Message", M2),
        _e("Person", CAROL, "AUTHORED", "Message", M3),
        _e("Person", DAN, "AUTHORED", "Message", M4),
        _e("Person", ADA, "AUTHORED", "Message", M5),
        _e("Message", M2, "REPLY_TO", "Message", M1),
    ],
)

JIRA = GraphDelta(
    nodes=[
        # Jira hides most emails: only Bob's is visible.
        _n("Person", JIRA_ADA, name="Ada Lovelace"),
        _n("Person", BOB, name="Bob Stone", email="bob@acme.io"),
        _n("Person", JIRA_CAROL, name="Carol D."),
        _n("Person", JIRA_DAN, name="Dan Wu"),
        _n("Project", "jira:project:ENG", name="Engineering"),
        _n("Project", "jira:project:BILL", name="Billing"),
        _n(
            "Ticket",
            ENG12,
            name="ENG-12: Migrate event bus to Kafka",
            text="See the RFC https://docs.google.com/document/d/rfc1 . "
            "Implementation lives in acme/api#9.",
            created_at="2026-09-01T11:00:00Z",
        ),
        _n(
            "Ticket",
            ENG15,
            name="ENG-15: Add rate limiting to login",
            text="The login endpoint needs rate limiting after brute force attempts by bots.",
            created_at="2026-09-03T09:00:00Z",
        ),
        _n(
            "Ticket",
            BILL3,
            name="BILL-3: EU invoice CSV export fails",
            text="Customers in the EU get an empty CSV file when they export invoices.",
            created_at="2026-09-04T15:00:00Z",
        ),
    ],
    edges=[
        _e("Ticket", ENG12, "PART_OF", "Project", "jira:project:ENG"),
        _e("Ticket", ENG15, "PART_OF", "Project", "jira:project:ENG"),
        _e("Ticket", BILL3, "PART_OF", "Project", "jira:project:BILL"),
        _e("Ticket", ENG12, "ASSIGNED_TO", "Person", JIRA_ADA),
        _e("Ticket", ENG15, "ASSIGNED_TO", "Person", JIRA_CAROL),
        _e("Ticket", BILL3, "ASSIGNED_TO", "Person", JIRA_DAN),
        _e("Person", BOB, "AUTHORED", "Ticket", ENG12),
        _e("Person", BOB, "OWNS", "Project", "jira:project:ENG"),
    ],
)

GITHUB = GraphDelta(
    nodes=[
        # Carol's GitHub email is public, Ada's and Bob's are not.
        _n("Person", GH_ADA, name="Ada Lovelace", login="ada-l"),
        _n("Person", GH_BOB, name="Bob Stone", login="bstone"),
        _n("Person", CAROL, name="Carol Diaz", email="carol@acme.io", login="cdiaz"),
        _n("Team", "github:org:acme", name="acme"),
        _n("Project", "github:repo:acme/api", name="acme/api"),
        _n(
            "Ticket",
            API7,
            name="acme/api#7: Login brute force",
            kind="issue",
            text="Bots keep brute forcing the login. We should rate limit login attempts per IP.",
            created_at="2026-09-02T12:00:00Z",
        ),
        _n(
            "Ticket",
            API9,
            name="acme/api#9: Kafka producer for the event bus",
            kind="pull_request",
            text="Implements ENG-12. Adds a Kafka producer behind the event bus interface.",
            created_at="2026-09-05T15:00:00Z",
        ),
    ],
    edges=[
        _e("Ticket", API7, "PART_OF", "Project", "github:repo:acme/api"),
        _e("Ticket", API9, "PART_OF", "Project", "github:repo:acme/api"),
        _e("Person", CAROL, "AUTHORED", "Ticket", API7),
        _e("Person", GH_ADA, "AUTHORED", "Ticket", API9),
        _e("Ticket", API9, "ASSIGNED_TO", "Person", GH_BOB),
        _e("Team", "github:org:acme", "OWNS", "Project", "github:repo:acme/api"),
    ],
)

GOOGLE = GraphDelta(
    nodes=[
        _n(
            "Document",
            RFC1,
            name="RFC: Event bus on Kafka",
            text="We propose replacing RabbitMQ with Kafka for the event bus. "
            "Kafka gives us replay and ordering per partition.",
            created_at="2026-08-30T10:00:00Z",
        ),
        _n(
            "Document",
            ADR4,
            name="ADR-004: Kafka for the event bus",
            text="Decision: adopt Kafka for the event bus. Context: ENG-12. "
            "Consequences: the team runs a Kafka cluster.",
            created_at="2026-09-02T10:00:00Z",
        ),
    ],
    edges=[
        _e("Person", ADA, "OWNS", "Document", RFC1),
        _e("Person", BOB, "OWNS", "Document", ADR4),
    ],
)

DELTAS: dict[str, GraphDelta] = {"slack": SLACK, "jira": JIRA, "github": GITHUB, "google": GOOGLE}

# ---- gold -------------------------------------------------------------------
# same_person and related are unordered pairs; references are directed.

GOLD: dict[str, set[tuple[str, str]]] = {
    "same_person": {
        (GH_ADA, ADA),
        (JIRA_ADA, ADA),
        (GH_BOB, BOB),
        (JIRA_CAROL, CAROL),  # hard: "Carol D." with no email
        (JIRA_DAN, DAN),
    },
    "references": {
        (M1, RFC1),
        (M2, ENG12),
        (M5, API9),
        (ENG12, RFC1),
        (ENG12, API9),
        (API9, ENG12),
        (ADR4, ENG12),
    },
    "related": {
        (M3, API7),
        (M3, ENG15),
        (ENG15, API7),
        (M4, BILL3),
        (M1, ADR4),
    },
    # Items a Decision node should be SOURCED_FROM.
    "decisions": {(M2,), (ADR4,)},
}

UNORDERED = {"same_person", "related"}


def load(store, graph: str) -> dict[str, dict[str, int]]:
    """Write the whole fake company into `graph`, one source at a time."""
    from .ingest import apply_delta

    return {source: apply_delta(store, graph, delta, source) for source, delta in DELTAS.items()}
