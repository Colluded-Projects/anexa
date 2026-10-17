import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "../test/helpers";
import { ApiError, errorDetail, request, setUnauthorizedHandler, tokenStore } from "./client";
import { workspaceApi } from "./index";

afterEach(() => setUnauthorizedHandler(null));

describe("request", () => {
  it("sends the bearer token and JSON body", async () => {
    tokenStore.set("tok123");
    const api = mockApi({ "POST /api/things": { status: 201, body: { id: "1" } } });

    const result = await request<{ id: string }>("/api/things", { method: "POST", body: { a: 1 } });

    expect(result).toEqual({ id: "1" });
    const call = api.calls[0]!;
    expect(call.headers.Authorization).toBe("Bearer tok123");
    expect(call.headers["Content-Type"]).toBe("application/json");
    expect(call.body).toEqual({ a: 1 });
  });

  it("omits the Authorization header when signed out", async () => {
    const api = mockApi({ "GET /api/health": { body: { status: "ok" } } });
    await request("/api/health");
    expect(api.calls[0]!.headers.Authorization).toBeUndefined();
  });

  it("builds a query string and skips empty values", async () => {
    const api = mockApi({ "GET /api/runs": { body: [] } });
    await request("/api/runs", { query: { kind: "action", status: "", target_id: undefined, limit: 50 } });
    expect(api.calls[0]!.url).toBe("/api/runs?kind=action&limit=50");
  });

  it("returns undefined for 204", async () => {
    mockApi({ "DELETE /api/things/1": { status: 204 } });
    await expect(request("/api/things/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("throws ApiError carrying the status and the server's detail", async () => {
    mockApi({ "DELETE /api/things/1": { status: 409, body: { detail: "connection is used by 2 actions" } } });
    const error = await request("/api/things/1", { method: "DELETE" }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(409);
    expect((error as ApiError).message).toBe("connection is used by 2 actions");
  });

  it("flattens FastAPI validation errors", async () => {
    mockApi({
      "POST /api/things": {
        status: 422,
        body: {
          detail: [
            { loc: ["body", "cron"], msg: "Field required", type: "missing" },
            { loc: ["body", "tasks", 0, "key"], msg: "String should match pattern", type: "x" },
          ],
        },
      },
    });
    await expect(request("/api/things", { method: "POST", body: {} })).rejects.toThrow(
      "cron: Field required; tasks.0.key: String should match pattern",
    );
  });

  it("falls back to a generic message when the body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" })),
    );
    await expect(request("/api/x")).rejects.toThrow("Bad Gateway");
  });

  it("reports an unreachable server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    const error = (await request("/api/x").catch((e: unknown) => e)) as ApiError;
    expect(error.status).toBe(0);
    expect(error.message).toMatch(/Cannot reach the server/);
  });

  it("on 401 clears the token and notifies the app", async () => {
    tokenStore.set("expired");
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockApi({ "GET /api/me": { status: 401, body: { detail: "Token expired" } } });

    await expect(request("/api/me")).rejects.toThrow("Token expired");

    expect(tokenStore.get()).toBeNull();
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("treats a 401 from login as wrong credentials, not a dead session", async () => {
    tokenStore.set("still-valid");
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockApi({ "POST /api/auth/login": { status: 401, body: { detail: "Invalid email or password" } } });

    await expect(
      request("/api/auth/login", { method: "POST", body: { email: "a", password: "b" } }),
    ).rejects.toThrow("Invalid email or password");

    expect(handler).not.toHaveBeenCalled();
    expect(tokenStore.get()).toBe("still-valid");
  });
});

describe("errorDetail", () => {
  it("uses the fallback for unknown shapes", () => {
    expect(errorDetail(null, "nope")).toBe("nope");
    expect(errorDetail({ detail: "" }, "nope")).toBe("nope");
    expect(errorDetail({ message: "x" }, "nope")).toBe("nope");
  });
});

describe("workspaceApi", () => {
  it("scopes paths to the workspace and uses the documented shapes", async () => {
    const api = mockApi({
      "POST /api/workspaces/w%2F1/actions/a1/run": { status: 202, body: { id: "r1" } },
      "DELETE /api/workspaces/w%2F1/graph/edges": { status: 204 },
      "GET /api/workspaces/w%2F1/schedules": { body: [] },
    });
    const ws = workspaceApi("w/1");

    await ws.actions.run("a1", { channel: "#eng" });
    expect(api.calls[0]!.body).toEqual({ input: { channel: "#eng" } });

    await ws.graph.removeEdge({ src: "n1", type: "MEMBER_OF", dst: "n2" });
    expect(api.calls[1]!.url).toBe("/api/workspaces/w%2F1/graph/edges?src=n1&type=MEMBER_OF&dst=n2");

    await ws.schedules.list("op1");
    expect(api.calls[2]!.url).toBe("/api/workspaces/w%2F1/schedules?operator_id=op1");
  });
});
