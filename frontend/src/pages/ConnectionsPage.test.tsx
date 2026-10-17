import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Connection } from "../api/types";
import { mockApi } from "../test/helpers";
import { BASE, CATALOG, renderInWorkspace } from "../test/render";
import { ConnectionsPage } from "./ConnectionsPage";

const SLACK: Connection = {
  id: "c1",
  name: "Eng Slack",
  connector: "slack",
  config: { default_channel: "#eng" },
  secret_fields: ["bot_token"],
  status: "untested",
  status_detail: "",
  created_at: "2026-10-01T00:00:00.000Z",
  updated_at: "2026-10-01T00:00:00.000Z",
};

const type = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("ConnectionsPage", () => {
  it("shows an empty state, then creates a connection from the catalog's fields", async () => {
    const api = mockApi({
      "GET /api/connectors": { body: CATALOG },
      [`GET ${BASE}/connections`]: { body: [] },
      [`POST ${BASE}/connections`]: { status: 201, body: SLACK },
    });
    renderInWorkspace(<ConnectionsPage />);

    expect(await screen.findByText("No connections yet")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "New connection" })[0]!);

    // Fields come from the selected connector; switching connector swaps them.
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByLabelText(/Bot token/)).toBeTruthy();
    fireEvent.change(dialog.getByLabelText("Connector"), { target: { value: "jira" } });
    expect(dialog.getByLabelText(/Site URL/)).toBeTruthy();
    expect(dialog.queryByLabelText(/Bot token/)).toBeNull();
    fireEvent.change(dialog.getByLabelText("Connector"), { target: { value: "slack" } });

    const token = dialog.getByLabelText(/Bot token/) as HTMLInputElement;
    expect(token.type).toBe("password");

    type(/^Name/, "Eng Slack");
    type(/Bot token/, "xoxb-secret");
    type("Default channel", "#eng");
    fireEvent.click(dialog.getByRole("button", { name: "Create connection" }));

    await waitFor(() => expect(api.find("POST", `${BASE}/connections`)).toHaveLength(1));
    expect(api.find("POST", `${BASE}/connections`)[0]!.body).toEqual({
      name: "Eng Slack",
      connector: "slack",
      config: { default_channel: "#eng" },
      secrets: { bot_token: "xoxb-secret" },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("blocks creation while a required secret is empty", async () => {
    const api = mockApi({
      "GET /api/connectors": { body: CATALOG },
      [`GET ${BASE}/connections`]: { body: [] },
    });
    renderInWorkspace(<ConnectionsPage />);
    await screen.findByText("No connections yet");
    fireEvent.click(screen.getAllByRole("button", { name: "New connection" })[0]!);

    type(/^Name/, "Eng Slack");
    fireEvent.click(screen.getByRole("button", { name: "Create connection" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Fill in: Bot token.");
    expect(api.find("POST", `${BASE}/connections`)).toHaveLength(0);
  });

  it("marks stored secrets as set and only sends them when changed", async () => {
    const api = mockApi({
      "GET /api/connectors": { body: CATALOG },
      [`GET ${BASE}/connections`]: { body: [SLACK] },
      [`PATCH ${BASE}/connections/c1`]: { body: SLACK },
    });
    renderInWorkspace(<ConnectionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit Eng Slack" }));
    const dialog = within(screen.getByRole("dialog"));
    const token = dialog.getByLabelText(/Bot token/) as HTMLInputElement;
    expect(token.value).toBe("");
    expect(token.placeholder).toMatch(/Saved/);
    expect(dialog.getByText("set")).toBeTruthy();
    expect((dialog.getByLabelText("Connector") as HTMLSelectElement).disabled).toBe(true);

    type("Default channel", "#platform");
    fireEvent.click(dialog.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.find("PATCH", `${BASE}/connections/c1`)).toHaveLength(1));
    expect(api.find("PATCH", `${BASE}/connections/c1`)[0]!.body).toEqual({
      name: "Eng Slack",
      config: { default_channel: "#platform" },
    });

    // Editing again and typing a new token sends just that secret.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(screen.getByRole("button", { name: "Edit Eng Slack" }));
    type(/Bot token/, "xoxb-rotated");
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.find("PATCH", `${BASE}/connections/c1`)).toHaveLength(2));
    expect(api.find("PATCH", `${BASE}/connections/c1`)[1]!.body).toMatchObject({
      secrets: { bot_token: "xoxb-rotated" },
    });
  });

  it("runs a connection test and shows the outcome", async () => {
    mockApi({
      "GET /api/connectors": { body: CATALOG },
      [`GET ${BASE}/connections`]: { body: [SLACK] },
      [`POST ${BASE}/connections/c1/test`]: {
        body: { ok: false, detail: "invalid_auth", identity: {} },
      },
    });
    renderInWorkspace(<ConnectionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Test Eng Slack" }));
    expect((await screen.findByText(/Failed: invalid_auth/)).textContent).toBeTruthy();
  });

  it("surfaces the conflict when deleting a connection that is in use", async () => {
    mockApi({
      "GET /api/connectors": { body: CATALOG },
      [`GET ${BASE}/connections`]: { body: [SLACK] },
      [`DELETE ${BASE}/connections/c1`]: {
        status: 409,
        body: { detail: "Connection is used by 1 action" },
      },
    });
    renderInWorkspace(<ConnectionsPage />);

    fireEvent.click(await screen.findByRole("button", { name: "Delete Eng Slack" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Connection is used by 1 action");
  });

  it("shows a load failure with a retry", async () => {
    mockApi({
      "GET /api/connectors": { body: CATALOG },
      [`GET ${BASE}/connections`]: { status: 403, body: { detail: "Not a member of this workspace" } },
    });
    renderInWorkspace(<ConnectionsPage />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Not a member of this workspace");
    expect(within(alert).getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});
