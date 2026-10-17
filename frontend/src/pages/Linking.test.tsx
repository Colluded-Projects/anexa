import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockApi } from "../test/helpers";
import { BASE, renderInWorkspace } from "../test/render";
import { GraphPage, LinkingPanel } from "./GraphPage";

const SCORE = {
  same_person: { expected: 5, found: 4, correct: 3, precision: 0.75, recall: 0.6 },
  references: { expected: 7, found: 7, correct: 7, precision: 1, recall: 1 },
};

describe("LinkingPanel", () => {
  it("loads the demo company, runs the linker and shows the score", async () => {
    const api = mockApi({
      [`POST ${BASE}/graph/demo`]: { status: 201, body: { loaded: { slack: { nodes: 10, edges: 5, skipped: 0 } } } },
      [`POST ${BASE}/graph/link`]: { body: { strategy: "rules", links: { SAME_AS: 4, REFERENCES: 7 } } },
      [`GET ${BASE}/graph/link/score`]: { body: SCORE },
    });
    renderInWorkspace(<LinkingPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Load demo company" }));
    await waitFor(() => expect(api.find("POST", `${BASE}/graph/demo`)).toHaveLength(1));
    expect(await screen.findByText(/Loaded demo company/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Run linker" }));
    await waitFor(() => expect(api.find("POST", `${BASE}/graph/link`)).toHaveLength(1));
    expect(await screen.findByText(/Strategy: rules/)).toBeTruthy();
    expect(screen.getByText("SAME_AS: 4")).toBeTruthy();

    expect(await screen.findByRole("cell", { name: "same_person" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "0.75" })).toBeTruthy();
  });
});

describe("GraphPage linker edges", () => {
  it("shows how a linked edge was found", async () => {
    const A = { id: "n1", label: "Message", name: "Decision: Kafka", key: "m1", source: "slack", url: null, props: {}, updated_at: "" };
    const B = { id: "n2", label: "Ticket", name: "ENG-12", key: "t1", source: "jira", url: null, props: {}, updated_at: "" };
    const EDGE = {
      src: "n1",
      type: "REFERENCES",
      dst: "n2",
      props: { source: "linker", method: "regex", confidence: 1, evidence: "tracked in ENG-12" },
    };
    mockApi({
      [`GET ${BASE}/graph/ontology`]: { body: { node_labels: { Message: "", Ticket: "" }, edge_types: { REFERENCES: "" } } },
      [`GET ${BASE}/graph/subgraph`]: { body: { nodes: [A, B], edges: [EDGE] } },
      [`GET ${BASE}/graph/nodes`]: { body: [A, B] },
      [`GET ${BASE}/graph/nodes/n1`]: { body: { ...A, edges: [EDGE], neighbors: [B] } },
    });
    renderInWorkspace(<GraphPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Message: Decision: Kafka" }));
    const badge = await screen.findByText("regex · 1");
    expect(badge.getAttribute("title")).toBe("tracked in ENG-12");
  });
});
