import type { JsonObject } from "../api/types";

export type ParsedObject = { ok: true; value: JsonObject } | { ok: false; error: string };

/** Parse text that must be a JSON object. Blank text is an empty object. */
export function parseJsonObject(text: string): ParsedObject {
  if (!text.trim()) return { ok: true, value: {} };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (cause) {
    return { ok: false, error: cause instanceof Error ? cause.message : "Invalid JSON" };
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, error: 'Must be a JSON object, like {"key": "value"}' };
  }
  return { ok: true, value: value as JsonObject };
}

export function prettyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}
