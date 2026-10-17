import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Action, Connection } from "../api/types";
import { mockApi } from "../test/helpers";
import { BASE, CATALOG, renderInWorkspace } from "../test/render";
import { ActionsPage } from "./ActionsPage";

const connection = (id: string, name: string, connector: string): Connection => ({
  id,
  name,
  connector,
  config: {},
  secret_fields: [],
  status: "ok",
  status_detail: "",
  created_at: "2026-10-01T00:00:00.000Z",
  updated_at: "2026-10-01T00:00:00.000Z",
});

const CONNECTIONS = [connection("c1", "Eng Slack", "slack"), connection("c2", "Platform Jira", "jira")];

const ACTION: Action = {
  id: "a1",
  name: "Post to #eng",
  description: "",
  connection_id: "c1",
  connection_name: "Eng Slack",
  connector: "slack",
  operation: "post_message",
  params: { channel: "#eng", text: "{{ input.text }}", unfurl: false },
  created_at: "2026-10-01T00:00:00.000Z",
  updated_at: "2026-10-01T00:00:00.000Z",
};

function routes(actions: Action[] = []) {
  return {
    "GET /api/connectors": { body: CATALOG },
    [`GET ${BASE}/connections`]: { body: CONNECTIONS },
    [`GET ${BASE}/actions`]: { body: actions },
  };
}

const type = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("ActionsPage", () => {
  it("asks for a connection first when there are none", async () => {
    mockApi({ ...routes(), [`GET ${BASE}/connections`]: { body: [] } });
    renderInWorkspace(<ActionsPage />);
    expect(await screen.findByText("Add a connection first")).toBeTruthy();
    expect((screen.getByRole("button", { name: "New action" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("builds the params form from the chosen connection's operation", async () => {
    const api = mockApi({ ...routes(), [`POST ${BASE}/actions`]: { status: 201, body: ACTION } });
    renderInWorkspace(<ActionsPage />);
    await screen.findByText("No actions yet");
    fireEvent.click(screen.getAllByRole("button", { name: "New action" })[0]!);
    const dialog = within(screen.getByRole("dialog"));

    // Slack is first: post_message has Channel + Text.
    expect(dialog.getByLabelText(/^Channel/)).toBeTruthy();
    expect(dialog.getByLabelText(/^Text/)).toBeTruthy();

    // Another operation on the same connector swaps the fields and applies defaults.
    fireEvent.change(dialog.getByLabelText(/^Operation/), { target: { value: "sync_users" } });
    expect(dialog.queryByLabelText(/^Channel/)).toBeNull();
    expect((dialog.getByLabelText("Limit") as HTMLInputElement).value).toBe("200");

    // Another connection offers that connector's operations.
    fireEvent.change(dialog.getByLabelText(/^Connection/), { target: { value: "c2" } });
    expect((dialog.getByLabelText(/^Operation/) as HTMLSelectElement).value).toBe("search_issues");
    expect(dialog.getByLabelText(/^JQL/)).toBeTruthy();

    type(/^Name/, "Open bugs");
    type(/^JQL/, "type = Bug AND project = {{ input.project }}");
    fireEvent.click(dialog.getByRole("button", { name: "Create action" }));

    await waitFor(() => expect(api.find("POST", `${BASE}/actions`)).toHaveLength(1));
    expect(api.find("POST", `${BASE}/actions`)[0]!.body).toEqual({
      name: "Open bugs",
      description: "",
      connection_id: "c2",
      operation: "search_issues",
      params: { jql: "type = Bug AND project = {{ input.project }}" },
    });
  });

  it("requires the operation's required params in form mode", async () => {
    const api = mockApi(routes());
    renderInWorkspace(<ActionsPage />);
    await screen.findByText("No actions yet");
    fireEvent.click(screen.getAllByRole("button", { name: "New action" })[0]!);

    type(/^Name/, "Post");
    type(/^Channel/, "#eng");
    fireEvent.click(screen.getByRole("button", { name: "Create action" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Fill in: Text.");
    expect(api.find("POST", `${BASE}/actions`)).toHaveLength(0);
  });

  it("round-trips params through the raw JSON editor, keeping undeclared keys", async () => {
    const api = mockApi({ ...routes([ACTION]), [`PATCH ${BASE}/actions/a1`]: { body: ACTION } });
    renderInWorkspace(<ActionsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Post to #eng" }));
    const dialog = within(screen.getByRole("dialog"));

    expect((dialog.getByLabelText(/^Channel/) as HTMLInputElement).value).toBe("#eng");
    expect(dialog.getByText(/extra param\(s\)/).textContent).toContain("unfurl");

    fireEvent.click(dialog.getByRole("button", { name: "Raw JSON" }));
    const editor = dialog.getByLabelText("Params as JSON") as HTMLTextAreaElement;
    expect(JSON.parse(editor.value)).toEqual(ACTION.params);

    // Invalid JSON cannot be switched back or saved.
    fireEvent.change(editor, { target: { value: '{"channel": ' } });
    fireEvent.click(dialog.getByRole("button", { name: "Form" }));
    expect(dialog.getByRole("alert").textContent).toMatch(/Fix the JSON/);
    expect(dialog.queryByLabelText(/^Channel/)).toBeNull();

    fireEvent.change(editor, {
      target: { value: '{"channel": "{{ input.channel }}", "text": "hi", "blocks": [1, 2]}' },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Form" }));
    expect((dialog.getByLabelText(/^Channel/) as HTMLInputElement).value).toBe("{{ input.channel }}");

    fireEvent.click(dialog.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.find("PATCH", `${BASE}/actions/a1`)).toHaveLength(1));
    expect(api.find("PATCH", `${BASE}/actions/a1`)[0]!.body).toMatchObject({
      params: { channel: "{{ input.channel }}", text: "hi", blocks: [1, 2] },
    });
  });

  it("runs an action with JSON input and opens the run", async () => {
    const api = mockApi({
      ...routes([ACTION]),
      [`POST ${BASE}/actions/a1/run`]: { status: 202, body: { id: "run42", status: "queued" } },
    });
    renderInWorkspace(<ActionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Run Post to #eng" }));
    const dialog = within(screen.getByRole("dialog"));
    const input = dialog.getByLabelText("Input");

    fireEvent.change(input, { target: { value: "[1]" } });
    expect((dialog.getByRole("button", { name: "Run now" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(input, { target: { value: '{"text": "deploy done"}' } });
    fireEvent.click(dialog.getByRole("button", { name: "Run now" }));

    expect(await screen.findByText("run page")).toBeTruthy();
    expect(api.find("POST", `${BASE}/actions/a1/run`)[0]!.body).toEqual({
      input: { text: "deploy done" },
    });
  });
});
