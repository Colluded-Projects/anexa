import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { mockApi } from "../test/helpers";
import { BASE, renderInWorkspace, WS } from "../test/render";
import { AgentsPage } from "./AgentsPage";
import { CypherBox, GraphPage } from "./GraphPage";
import { SchedulesPage } from "./SchedulesPage";
import { mcpConfig, mcpStdioConfig, SettingsPage } from "./SettingsPage";

const OPERATOR = {
  id: "op1",
  name: "Weekly digest",
  description: "",
  enabled: true,
  tasks: [],
  created_at: "",
  updated_at: "",
};

describe("SchedulesPage", () => {
  it("validates cron client-side, describes it, and creates the schedule", async () => {
    const api = mockApi({
      [`GET ${BASE}/schedules`]: { body: [] },
      [`GET ${BASE}/operators`]: { body: [OPERATOR] },
      [`POST ${BASE}/schedules`]: { status: 201, body: {} },
    });
    renderInWorkspace(<SchedulesPage />);
    await screen.findByText("Nothing is scheduled");
    fireEvent.click(screen.getAllByRole("button", { name: "New schedule" })[0]!);
    const dialog = within(screen.getByRole("dialog"));
    const cron = dialog.getByLabelText("Cron expression");
    const submit = dialog.getByRole("button", { name: "Create schedule" }) as HTMLButtonElement;

    fireEvent.change(cron, { target: { value: "0 9 * *" } });
    expect(dialog.getByText(/Expected 5 fields/)).toBeTruthy();
    expect(submit.disabled).toBe(true);

    fireEvent.change(cron, { target: { value: "30 8 * * 1-5" } });
    expect(dialog.getByText("At 08:30 on Monday through Friday")).toBeTruthy();
    expect(submit.disabled).toBe(false);

    fireEvent.change(dialog.getByLabelText("Timezone"), { target: { value: "Europe/Berlin" } });
    fireEvent.click(submit);
    await waitFor(() => expect(api.find("POST", `${BASE}/schedules`)).toHaveLength(1));
    expect(api.find("POST", `${BASE}/schedules`)[0]!.body).toEqual({
      operator_id: "op1",
      cron: "30 8 * * 1-5",
      timezone: "Europe/Berlin",
      enabled: true,
      input: {},
    });
  });

  it("shows the server's rejection of a cron it does not accept", async () => {
    mockApi({
      [`GET ${BASE}/schedules`]: { body: [] },
      [`GET ${BASE}/operators`]: { body: [OPERATOR] },
      [`POST ${BASE}/schedules`]: { status: 422, body: { detail: "unknown timezone: 'Mars/Olympus'" } },
    });
    renderInWorkspace(<SchedulesPage />);
    await screen.findByText("Nothing is scheduled");
    fireEvent.click(screen.getAllByRole("button", { name: "New schedule" })[0]!);
    fireEvent.click(screen.getByRole("button", { name: "Create schedule" }));
    expect((await screen.findByRole("alert")).textContent).toContain("unknown timezone");
  });
});

describe("AgentsPage", () => {
  it("labels agents as not connected and saves only a definition", async () => {
    const api = mockApi({
      [`GET ${BASE}/agents`]: { body: [] },
      [`GET ${BASE}/actions`]: {
        body: [{ id: "a1", name: "Post to #eng", connector: "slack", operation: "post_message" }],
      },
      [`GET ${BASE}/operators`]: { body: [OPERATOR] },
      [`POST ${BASE}/agents`]: { status: 201, body: {} },
    });
    renderInWorkspace(<AgentsPage />);
    expect(await screen.findByText("Agents are placeholders for now.")).toBeTruthy();

    fireEvent.click(screen.getAllByRole("button", { name: "New agent" })[0]!);
    const dialog = within(screen.getByRole("dialog"));
    fireEvent.change(dialog.getByLabelText(/^Name/), { target: { value: "Triage" } });
    fireEvent.change(dialog.getByLabelText("Provider"), { target: { value: "jev" } });
    fireEvent.click(dialog.getByLabelText(/Post to #eng/));
    fireEvent.click(dialog.getByLabelText(/Weekly digest/));
    fireEvent.click(dialog.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(api.find("POST", `${BASE}/agents`)).toHaveLength(1));
    expect(api.find("POST", `${BASE}/agents`)[0]!.body).toEqual({
      name: "Triage",
      description: "",
      provider: "jev",
      model: "",
      instructions: "",
      action_ids: ["a1"],
      operator_ids: ["op1"],
    });
  });

  it("shows the Not connected badge on every agent", async () => {
    mockApi({
      [`GET ${BASE}/agents`]: {
        body: [
          {
            id: "g1",
            name: "Triage",
            description: "",
            provider: "openrouter",
            model: "anthropic/claude-sonnet-5",
            instructions: "",
            action_ids: ["gone"],
            operator_ids: [],
            status: "not_connected",
            created_at: "",
            updated_at: "",
          },
        ],
      },
      [`GET ${BASE}/actions`]: { body: [] },
      [`GET ${BASE}/operators`]: { body: [] },
    });
    renderInWorkspace(<AgentsPage />);
    expect(await screen.findByText("Not connected")).toBeTruthy();
    expect(screen.getByText(/OpenRouter · anthropic\/claude-sonnet-5/)).toBeTruthy();
    expect(screen.getByText("deleted action")).toBeTruthy();
  });
});

describe("graph", () => {
  const ONTOLOGY = {
    node_labels: { Person: "Someone", Team: "A group" },
    edge_types: { MEMBER_OF: "Person -> Team" },
  };
  const ADA = { id: "n1", label: "Person", name: "Ada", key: "email:ada@acme.com", source: "slack", url: null, props: { title: "CTO" }, updated_at: "" };
  const PLATFORM = { id: "n2", label: "Team", name: "Platform", key: "manual:n2", source: "manual", url: null, props: {}, updated_at: "" };
  const EDGE = { src: "n1", type: "MEMBER_OF", dst: "n2", props: {} };

  it("draws the subgraph and opens a node's details, edges and neighbours", async () => {
    const api = mockApi({
      [`GET ${BASE}/graph/ontology`]: { body: ONTOLOGY },
      [`GET ${BASE}/graph/subgraph`]: { body: { nodes: [ADA, PLATFORM], edges: [EDGE] } },
      [`GET ${BASE}/graph/nodes`]: { body: [ADA, PLATFORM] },
      [`GET ${BASE}/graph/nodes/n1`]: { body: { ...ADA, edges: [EDGE], neighbors: [PLATFORM] } },
      [`DELETE ${BASE}/graph/edges`]: { status: 204 },
    });
    renderInWorkspace(<GraphPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Person: Ada" }));
    expect(await screen.findByRole("heading", { name: "Ada" })).toBeTruthy();
    expect(screen.getByText("email:ada@acme.com")).toBeTruthy();
    expect(screen.getByText("CTO")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Platform" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Remove MEMBER_OF edge to Platform" }));
    await waitFor(() => expect(api.find("DELETE", `${BASE}/graph/edges`)).toHaveLength(1));
    expect(api.find("DELETE", `${BASE}/graph/edges`)[0]!.url).toContain("src=n1&type=MEMBER_OF&dst=n2");
  });

  it("adds a node with a label from the ontology", async () => {
    const api = mockApi({
      [`GET ${BASE}/graph/ontology`]: { body: ONTOLOGY },
      [`GET ${BASE}/graph/subgraph`]: { body: { nodes: [], edges: [] } },
      [`GET ${BASE}/graph/nodes`]: { body: [] },
      [`POST ${BASE}/graph/nodes`]: { status: 201, body: PLATFORM },
      [`GET ${BASE}/graph/nodes/n2`]: { body: { ...PLATFORM, edges: [], neighbors: [] } },
    });
    renderInWorkspace(<GraphPage />);
    await screen.findByText("The graph is empty");

    fireEvent.click(screen.getAllByRole("button", { name: "Add node" })[0]!);
    const dialog = within(screen.getByRole("dialog"));
    const label = dialog.getByLabelText("Label") as HTMLSelectElement;
    expect([...label.options].map((option) => option.value)).toEqual(["Person", "Team"]);
    fireEvent.change(label, { target: { value: "Team" } });
    fireEvent.change(dialog.getByLabelText(/^Name/), { target: { value: "Platform" } });
    fireEvent.change(dialog.getByLabelText("Properties"), { target: { value: '{"size": 6}' } });
    fireEvent.click(dialog.getByRole("button", { name: "Add node" }));

    await waitFor(() => expect(api.find("POST", `${BASE}/graph/nodes`)).toHaveLength(1));
    expect(api.find("POST", `${BASE}/graph/nodes`)[0]!.body).toEqual({
      label: "Team",
      name: "Platform",
      props: { size: 6 },
    });
  });

  it("renders Cypher rows as a table", async () => {
    mockApi({
      [`POST ${BASE}/graph/query`]: {
        body: { rows: [{ "p.name": "Ada", teams: ["Platform"] }, { "p.name": "Lin", teams: [] }] },
      },
    });
    renderInWorkspace(<CypherBox />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    expect(await screen.findByRole("columnheader", { name: "p.name" })).toBeTruthy();
    expect(screen.getByText("Ada")).toBeTruthy();
    expect(screen.getByText('["Platform"]')).toBeTruthy();
    expect(screen.getByText("2 row(s)")).toBeTruthy();
  });

  it("explains a 501 from the memory backend", async () => {
    mockApi({ [`POST ${BASE}/graph/query`]: { status: 501, body: { detail: "raw Cypher needs FalkorDB" } } });
    renderInWorkspace(<CypherBox />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect(await screen.findByText(/Cypher queries need the FalkorDB backend/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a 422 as a query error", async () => {
    mockApi({ [`POST ${BASE}/graph/query`]: { status: 422, body: { detail: "Invalid input 'MATC'" } } });
    renderInWorkspace(<CypherBox />);
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Query error: Invalid input 'MATC'");
  });
});

describe("SettingsPage", () => {
  const members = [
    { user_id: "u1", email: "ada@acme.com", name: "Ada", role: "owner" },
    { user_id: "u2", email: "lin@acme.com", name: "Lin", role: "member" },
  ];

  it("shows a new API key once, with copy, and fills it into the MCP snippet", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    mockApi({
      [`GET ${BASE}/members`]: { body: members },
      [`GET ${BASE}/api-keys`]: { body: [] },
      [`POST ${BASE}/api-keys`]: {
        status: 201,
        body: { id: "k1", name: "Laptop", prefix: "axk_abc12345", created_at: "", last_used_at: null, key: "axk_abc12345_full_secret" },
      },
    });
    renderInWorkspace(<SettingsPage />);
    await screen.findByText("No keys yet.");
    expect(screen.getByLabelText("MCP configuration").textContent).toContain("<your API key>");

    fireEvent.change(screen.getByLabelText("New key name"), { target: { value: "Laptop" } });
    fireEvent.click(screen.getByRole("button", { name: "Create key" }));

    expect(await screen.findByText(/It will not be shown again/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Copy key" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("axk_abc12345_full_secret"));

    const config = JSON.parse(screen.getByLabelText("MCP configuration").textContent ?? "");
    expect(config.mcpServers.anexa).toEqual({
      type: "http",
      url: `${window.location.origin}/mcp`,
      headers: { Authorization: "Bearer axk_abc12345_full_secret" },
    });
  });

  it("generates a paste-ready MCP config with a fresh bearer token in one click", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const api = mockApi({
      [`GET ${BASE}/members`]: { body: members },
      [`GET ${BASE}/api-keys`]: { body: [] },
      [`POST ${BASE}/api-keys`]: {
        status: 201,
        body: { id: "k9", name: "Claude Code (MCP)", prefix: "axk_gen", created_at: "", last_used_at: null, key: "axk_generated_secret" },
      },
    });
    renderInWorkspace(<SettingsPage />);
    await screen.findByText("No keys yet.");
    const listCalls = () => api.calls.filter((c) => c.method === "GET" && c.url.endsWith("/api-keys")).length;
    const before = listCalls();

    fireEvent.change(screen.getByLabelText("MCP server URL as seen from your machine"), {
      target: { value: "http://box:8000/mcp" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate MCP config" }));

    expect(await screen.findByText(/the key is not shown again/)).toBeTruthy();
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Claude Code (MCP)" });
    const text = screen.getByLabelText("MCP configuration").textContent ?? "";
    expect(JSON.parse(text).mcpServers.anexa).toEqual({
      type: "http",
      url: "http://box:8000/mcp",
      headers: { Authorization: "Bearer axk_generated_secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Copy config" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(text));
    // The key list reloads so the new key can be revoked from this page.
    await waitFor(() => expect(listCalls()).toBeGreaterThan(before));
  });

  it("lets owners add and remove members", async () => {
    const api = mockApi({
      [`GET ${BASE}/members`]: { body: members },
      [`GET ${BASE}/api-keys`]: { body: [] },
      [`POST ${BASE}/members`]: { status: 404, body: { detail: "No user with that email" } },
    });
    renderInWorkspace(<SettingsPage />);
    expect(await screen.findByRole("button", { name: "Remove lin@acme.com" })).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Add a member by email"), { target: { value: "new@acme.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toContain("No user with that email");
    expect(api.find("POST", `${BASE}/members`)[0]!.body).toEqual({ email: "new@acme.com", role: "member" });
  });

  it("hides member management from non-owners", async () => {
    mockApi({
      [`GET ${BASE}/members`]: { body: members },
      [`GET ${BASE}/api-keys`]: { body: [] },
    });
    renderInWorkspace(<SettingsPage />, { workspace: { ...WS, role: "member" } });
    expect(await screen.findByText("Only workspace owners can add or remove members.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Remove lin@acme.com" })).toBeNull();
    expect(screen.queryByLabelText("Add a member by email")).toBeNull();
  });
});

describe("mcpConfig", () => {
  it("is valid JSON carrying the key as a bearer token", () => {
    expect(JSON.parse(mcpConfig("http://x:1/mcp", "axk_k")).mcpServers.anexa).toEqual({
      type: "http",
      url: "http://x:1/mcp",
      headers: { Authorization: "Bearer axk_k" },
    });
  });

  it("offers a local stdio variant with the documented command", () => {
    const server = JSON.parse(mcpStdioConfig("http://x:1", "axk_k")).mcpServers.anexa;
    expect(server.args).toEqual(["run", "--directory", "<repo>/backend", "anexa-mcp"]);
    expect(server.env).toEqual({ ANEXA_API_URL: "http://x:1", ANEXA_API_KEY: "axk_k" });
  });
});
