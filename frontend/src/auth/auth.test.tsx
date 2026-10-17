import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { tokenStore } from "../api/client";
import { AppRoutes } from "../App";
import { mockApi } from "../test/helpers";
import { WS } from "../test/render";
import { AuthProvider } from "./AuthContext";

const USER = { id: "u1", email: "ada@acme.com", name: "Ada", created_at: "2026-10-01T00:00:00.000Z" };
const SUMMARY = {
  counts: { connections: 2, actions: 0, operators: 0, schedules: 0, agents: 0, runs: 0 },
  runs_by_status: { queued: 0, running: 0, succeeded: 0, failed: 0 },
  recent_runs: [],
  graph: {},
};
const signedIn = {
  "GET /api/me": { body: { user: USER, workspaces: [WS] } },
  "GET /api/workspaces/ws1/summary": { body: SUMMARY },
};

function renderApp(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const type = (label: string | RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("authentication", () => {
  it("sends a signed-out visitor to the login page", async () => {
    const api = mockApi({});
    renderApp("/operators");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(api.calls).toHaveLength(0);
  });

  it("logs in, stores the token and shows the workspace", async () => {
    const api = mockApi({
      ...signedIn,
      "POST /api/auth/login": { body: { access_token: "jwt-1", token_type: "bearer", user: USER } },
    });
    renderApp("/login");

    type("Email", "ada@acme.com");
    type("Password", "correct horse");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "Acme" })).toBeTruthy();
    expect(tokenStore.get()).toBe("jwt-1");
    expect(api.find("POST", "/api/auth/login")[0]!.body).toEqual({
      email: "ada@acme.com",
      password: "correct horse",
    });
    expect(api.find("GET", "/api/me")[0]!.headers.Authorization).toBe("Bearer jwt-1");
    expect(screen.getByText("ada@acme.com")).toBeTruthy();
  });

  it("shows the server's message for wrong credentials and stays on the form", async () => {
    mockApi({ "POST /api/auth/login": { status: 401, body: { detail: "Invalid email or password" } } });
    renderApp("/login");

    type("Email", "ada@acme.com");
    type("Password", "wrong-password");
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Invalid email or password");
    expect(tokenStore.get()).toBeNull();
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy();
  });

  it("signs up with a workspace name and lands in the app", async () => {
    const api = mockApi({
      ...signedIn,
      "POST /api/auth/signup": {
        status: 201,
        body: { access_token: "jwt-2", token_type: "bearer", user: USER, workspace: WS },
      },
    });
    renderApp("/signup");

    type("Your name", "Ada");
    type("Email", "ada@acme.com");
    type("Password", "long enough");
    type("Workspace name", "Acme");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByRole("heading", { name: "Acme" })).toBeTruthy();
    expect(api.find("POST", "/api/auth/signup")[0]!.body).toEqual({
      name: "Ada",
      email: "ada@acme.com",
      password: "long enough",
      workspace_name: "Acme",
    });
    expect(tokenStore.get()).toBe("jwt-2");
  });

  it("rejects a short password before calling the server", async () => {
    const api = mockApi({});
    renderApp("/signup");

    type("Your name", "Ada");
    type("Email", "ada@acme.com");
    type("Password", "short");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect((await screen.findByRole("alert")).textContent).toMatch(/at least 8 characters/);
    expect(api.calls).toHaveLength(0);
  });

  it("shows a duplicate-email conflict from signup", async () => {
    mockApi({ "POST /api/auth/signup": { status: 409, body: { detail: "Email already registered" } } });
    renderApp("/signup");

    type("Your name", "Ada");
    type("Email", "ada@acme.com");
    type("Password", "long enough");
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect((await screen.findByRole("alert")).textContent).toContain("Email already registered");
  });

  it("restores a stored session on load", async () => {
    tokenStore.set("jwt-old");
    mockApi(signedIn);
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Acme" })).toBeTruthy();
  });

  it("returns to login when the stored token is rejected", async () => {
    tokenStore.set("jwt-expired");
    mockApi({ "GET /api/me": { status: 401, body: { detail: "Token expired" } } });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(tokenStore.get()).toBeNull();
  });

  it("returns to login when any later request comes back 401", async () => {
    tokenStore.set("jwt-revoked-soon");
    mockApi({
      "GET /api/me": { body: { user: USER, workspaces: [WS] } },
      "GET /api/workspaces/ws1/summary": { status: 401, body: { detail: "Not authenticated" } },
    });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeTruthy();
    expect(tokenStore.get()).toBeNull();
  });

  it("signs out from the shell", async () => {
    tokenStore.set("jwt-1");
    mockApi(signedIn);
    renderApp("/");
    fireEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeTruthy());
    expect(tokenStore.get()).toBeNull();
  });

  it("creates a workspace from the switcher and switches to it", async () => {
    tokenStore.set("jwt-1");
    const beta = { ...WS, id: "ws2", name: "Beta", slug: "beta" };
    const api = mockApi({
      ...signedIn,
      "POST /api/workspaces": { status: 201, body: beta },
      "GET /api/workspaces/ws2/summary": { body: SUMMARY },
    });
    renderApp("/");
    await screen.findByRole("heading", { name: "Acme" });

    fireEvent.change(screen.getByLabelText("Workspace"), { target: { value: "__new__" } });
    type("Workspace name", "Beta");
    fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));

    expect(await screen.findByRole("heading", { name: "Beta" })).toBeTruthy();
    expect(api.find("POST", "/api/workspaces")[0]!.body).toEqual({ name: "Beta" });
    expect(api.find("GET", "/api/workspaces/ws2/summary")).toHaveLength(1);
  });
});
