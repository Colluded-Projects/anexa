const TOKEN_KEY = "orgraph.token";

export const tokenStore = {
  get(): string | null {
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string): void {
    try {
      localStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable: the session lasts until reload */
    }
  },
  clear(): void {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* nothing to clear */
    }
  },
};

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
  }
}

let unauthorizedHandler: (() => void) | null = null;

/** Called when an authenticated request comes back 401 (expired or revoked session). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** Turn an error body into one readable line. Handles `{detail: string}` and
 * FastAPI's 422 shape, where `detail` is a list of `{loc, msg}`. */
export function errorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string" && detail) return detail;
    if (Array.isArray(detail)) {
      const parts = detail.map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          const { loc, msg } = item as { loc?: unknown[]; msg: unknown };
          const where = Array.isArray(loc) ? loc.filter((p) => p !== "body").join(".") : "";
          return where ? `${where}: ${String(msg)}` : String(msg);
        }
        return String(item);
      });
      if (parts.length) return parts.join("; ");
    }
  }
  return fallback;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(0, "Cannot reach the server. Check that the API is running.");
  }

  if (response.status === 204) return undefined as T;

  let parsed: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    // A 401 from login/signup means wrong credentials, not a dead session.
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      tokenStore.clear();
      unauthorizedHandler?.();
    }
    const fallback = response.statusText || `Request failed (${response.status})`;
    throw new ApiError(response.status, errorDetail(parsed, fallback));
  }
  return parsed as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong.";
}
