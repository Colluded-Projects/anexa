"""Shape of a workspace's company graph.

Every node carries: `key` (stable identity within its label), `name`, `source`
(connector key or "manual"), optional `url`, and `updated_at`. Connectors
describe what they found as a GraphDelta; graph.ingest applies it.
"""

from __future__ import annotations

NODE_LABELS: dict[str, str] = {
    "Person": "Someone who works at or with the company",
    "Team": "A group of people: org team, Slack channel, GitHub team",
    "Project": "A unit of work: Jira project, GitHub repository, initiative",
    "Document": "Written material: Google Doc, spec, wiki page",
    "Ticket": "A tracked work item: Jira issue, GitHub issue or pull request",
    "Decision": "A decision that was made, with its rationale",
    "Message": "A chat message or comment: Slack message, ticket comment",
    "Topic": "A subject people talk and write about, found by the linker",
}

EDGE_TYPES: dict[str, str] = {
    "MEMBER_OF": "Person -> Team",
    "WORKS_ON": "Person or Team -> Project",
    "OWNS": "Person or Team -> Project, Document or Ticket",
    "AUTHORED": "Person -> Document, Ticket or Decision",
    "ASSIGNED_TO": "Ticket -> Person",
    "PART_OF": "Ticket or Document -> Project; Team -> Team",
    "REPORTS_TO": "Person -> Person",
    "DECIDED": "Person or Team -> Decision",
    "AFFECTS": "Decision -> Project, Team, Document or Ticket",
    "REFERENCES": "any -> any",
    "POSTED_IN": "Message -> Team (Slack channel)",
    "REPLY_TO": "Message -> Message",
    "MENTIONS": "Message, Ticket or Document -> Person",
    # Written by the linker (graph.linking); props carry method, confidence, evidence.
    "SAME_AS": "Person -> Person (one human, two accounts)",
    "ABOUT": "Message, Ticket, Document or Decision -> Topic",
    "KNOWS_ABOUT": "Person -> Topic or Project",
    "SOURCED_FROM": "Decision -> Message, Ticket or Document it came from",
    "RELATED_TO": "any -> any (inferred, weaker than REFERENCES)",
}

# Node props holding free text (message body, ticket description, doc content).
TEXT_PROP = "text"


def entity_key(source: str, kind: str, external_id: str) -> str:
    """Identity for an entity that only exists in one system, e.g.
    entity_key("github", "repo", "acme/api") -> "github:repo:acme/api"."""
    return f"{source}:{kind}:{external_id}"


def person_key(email: str | None, source: str, external_id: str) -> str:
    """People are merged across systems by email when one is known."""
    if email:
        return f"email:{email.strip().lower()}"
    return entity_key(source, "user", external_id)
