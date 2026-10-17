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
      [`POST ${BASE}/graph/link`]: { body: { strategy: "rules", links: { SAME_AS: 4, REFERENCES: 7 }, llm: "off" } },
      [`GET ${BASE}/graph/link/score`]: { body: SCORE },
      [`GET ${BASE}/graph/link/review`]: { body: [] },
    });
    renderInWorkspace(<LinkingPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Load demo company" }));
    await waitFor(() => expect(api.find("POST", `${BASE}/graph/demo`)).toHaveLength(1));
    expect(await screen.findByText(/Loaded demo company/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Run linker" }));
    await waitFor(() => expect(api.find("POST", `${BASE}/graph/link`)).toHaveLength(1));
    expect(await screen.findByText(/Strategy: rules/)).toBeTruthy();
    expect(screen.getByText("SAME_AS: 4")).toBeTruthy();
    expect(screen.getByText("LLM: off")).toBeTruthy();

    expect(await screen.findByRole("cell", { name: "same_person" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "0.75" })).toBeTruthy();
  });

  it("lists who knows about a topic", async () => {
    const api = mockApi({
      [`GET ${BASE}/graph/experts`]: {
        body: [
          { name: "Ada Lovelace", key: "email:ada@acme.io", score: 5 },
          { name: "Bob Stone", key: "email:bob@acme.io", score: 4 },
        ],
      },
    });
    renderInWorkspace(<LinkingPanel />);

    fireEvent.change(screen.getByLabelText("Who knows about…"), { target: { value: "kafka" } });
    fireEvent.click(screen.getByRole("button", { name: "Find experts" }));
    await waitFor(() => expect(api.find("GET", `${BASE}/graph/experts`)).toHaveLength(1));
    expect(api.find("GET", `${BASE}/graph/experts`)[0]?.url).toContain("topic=kafka");
    expect(await screen.findByText("Ada Lovelace (5)")).toBeTruthy();
    expect(screen.getByText("Bob Stone (4)")).toBeTruthy();
  });
});

const REVIEW = [
  {
    src: "n1", src_name: "login is slow", type: "RELATED_TO", dst: "n2", dst_name: "ENG-15",
    method: "llm", confidence: 0.4, evidence: "rate limiting",
  },
  {
    src: "n3", src_name: "Carol D.", type: "SAME_AS", dst: "n4", dst_name: "Carol Diaz",
    method: "llm", confidence: 0.6, evidence: "same first name",
  },
];

describe("LinkingPanel review", () => {
  it("lists unsure links and accepts or rejects them", async () => {
    let queue = REVIEW;
    const api = mockApi({
      [`POST ${BASE}/graph/link`]: { body: { strategy: "hybrid", links: { SAME_AS: 1 }, llm: "on" } },
      [`GET ${BASE}/graph/link/score`]: { body: SCORE },
      [`GET ${BASE}/graph/link/review`]: () => ({ body: queue }),
      [`POST ${BASE}/graph/link/review/accept`]: (call) => {
        queue = queue.filter((row) => row.src !== (call.body as { src: string }).src);
        return { body: { src: "n1", type: "RELATED_TO", dst: "n2", props: {} } };
      },
      [`DELETE ${BASE}/graph/edges`]: (call) => {
        queue = queue.filter((row) => !call.url.includes(`src=${row.src}`));
        return { status: 204 };
      },
    });
    renderInWorkspace(<LinkingPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Run linker" }));
    expect(await screen.findByText("LLM: on")).toBeTruthy();
    expect(await screen.findByText(/login is slow/)).toBeTruthy();
    expect(screen.getByText("rate limiting")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Accept login is slow RELATED_TO ENG-15" }));
    await waitFor(() => expect(api.find("POST", `${BASE}/graph/link/review/accept`)).toHaveLength(1));
    expect(api.find("POST", `${BASE}/graph/link/review/accept`)[0]?.body).toEqual({
      src: "n1", type: "RELATED_TO", dst: "n2",
    });
    await waitFor(() => expect(screen.queryByText(/login is slow/)).toBeNull());

    fireEvent.click(screen.getByRole("button", { name: "Reject Carol D. SAME_AS Carol Diaz" }));
    await waitFor(() => expect(api.find("DELETE", `${BASE}/graph/edges`)).toHaveLength(1));
    expect(api.find("DELETE", `${BASE}/graph/edges`)[0]?.url).toContain("type=SAME_AS");
    expect(await screen.findByText("Nothing to review.")).toBeTruthy();
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
