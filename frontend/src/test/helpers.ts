import { vi } from "vitest";

export interface MockRoute {
  status?: number;
  body?: unknown;
}

export interface RecordedCall {
  method: string;
  url: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
}

type Handler = MockRoute | ((call: RecordedCall) => MockRoute);

/** Replace global fetch with a table of `"METHOD /path"` → response.
 * The path is matched without its query string. Unmatched calls answer 404. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: RecordedCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.split("?")[0] ?? url;
    const call: RecordedCall = {
      method,
      url,
      path,
      headers: (init?.headers ?? {}) as Record<string, string>,
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    };
    calls.push(call);
    const handler = routes[`${method} ${path}`];
    const route: MockRoute =
      handler === undefined
        ? { status: 404, body: { detail: `no mock for ${method} ${path}` } }
        : typeof handler === "function"
          ? handler(call)
          : handler;
    const status = route.status ?? 200;
    const text = status === 204 || route.body === undefined ? "" : JSON.stringify(route.body);
    return new Response(status === 204 ? null : text, {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    fetchMock,
    find: (method: string, path: string) =>
      calls.filter((call) => call.method === method && call.path === path),
  };
}
