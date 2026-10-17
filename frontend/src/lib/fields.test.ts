import { describe, expect, it } from "vitest";
import type { FieldSpec } from "../api/types";
import {
  buildConnectionPayload,
  collectValues,
  extraValues,
  initialValues,
  missingRequired,
} from "./fields";

function field(overrides: Partial<FieldSpec> & { name: string }): FieldSpec {
  return {
    label: overrides.name,
    type: "string",
    required: false,
    secret: false,
    help: "",
    default: null,
    options: [],
    placeholder: "",
    ...overrides,
  };
}

const jira = [
  field({ name: "base_url", label: "Site URL", required: true }),
  field({ name: "email", label: "Email", required: true }),
  field({ name: "api_token", label: "API token", required: true, secret: true }),
  field({ name: "webhook_secret", label: "Webhook secret", secret: true }),
  field({ name: "page_size", type: "number", default: 50 }),
  field({ name: "verify_tls", type: "boolean", default: true }),
];

describe("initialValues", () => {
  it("uses stored values, then defaults, then blanks", () => {
    expect(initialValues(jira, { base_url: "https://acme.atlassian.net", page_size: 10 })).toEqual({
      base_url: "https://acme.atlassian.net",
      email: "",
      api_token: "",
      webhook_secret: "",
      page_size: "10",
      verify_tls: true,
    });
  });
});

describe("collectValues", () => {
  it("drops blanks and converts numbers", () => {
    const values = { ...initialValues(jira), base_url: " https://x ", email: "", page_size: "25" };
    expect(collectValues(jira, values)).toEqual({
      base_url: " https://x ",
      page_size: 25,
      verify_tls: true,
    });
  });

  it("keeps a template in a number field as text", () => {
    const fields = [field({ name: "limit", type: "number" })];
    expect(collectValues(fields, { limit: "{{ input.limit }}" })).toEqual({
      limit: "{{ input.limit }}",
    });
  });

  it("only sends a false boolean when the default is true", () => {
    const fields = [
      field({ name: "a", type: "boolean", default: true }),
      field({ name: "b", type: "boolean" }),
    ];
    expect(collectValues(fields, { a: false, b: false })).toEqual({ a: false });
    expect(collectValues(fields, { a: true, b: true })).toEqual({ a: true, b: true });
  });
});

describe("extraValues", () => {
  it("returns keys that no field describes", () => {
    expect(extraValues(jira, { email: "a@b.c", custom: [1, 2] })).toEqual({ custom: [1, 2] });
  });
});

describe("missingRequired", () => {
  it("lists empty required fields, including unset secrets", () => {
    expect(missingRequired(jira, initialValues(jira))).toEqual(["Site URL", "Email", "API token"]);
  });

  it("treats a stored secret as filled unless it is being cleared", () => {
    const values = { ...initialValues(jira), base_url: "u", email: "e" };
    expect(missingRequired(jira, values, {}, ["api_token"])).toEqual([]);
    expect(missingRequired(jira, values, { api_token: null }, ["api_token"])).toEqual(["API token"]);
    expect(missingRequired(jira, values, { api_token: "new" }, [])).toEqual([]);
  });
});

describe("buildConnectionPayload", () => {
  const values = { ...initialValues(jira), base_url: "https://x", email: "me@x.io" };

  it("puts non-secret fields in config and omits untouched secrets", () => {
    expect(buildConnectionPayload(jira, values, {})).toEqual({
      config: { base_url: "https://x", email: "me@x.io", page_size: 50, verify_tls: true },
    });
  });

  it("sends only the secrets that changed, with null to clear one", () => {
    const payload = buildConnectionPayload(jira, values, { api_token: "tok", webhook_secret: null });
    expect(payload.secrets).toEqual({ api_token: "tok", webhook_secret: null });
    expect(payload.config).not.toHaveProperty("api_token");
  });

  it("never sends a blank secret", () => {
    expect(buildConnectionPayload(jira, values, { api_token: "" })).not.toHaveProperty("secrets");
  });
});
