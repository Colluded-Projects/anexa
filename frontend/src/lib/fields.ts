import type { FieldSpec, Json, JsonObject } from "../api/types";

/** Form state for a list of FieldSpec: text controls hold strings, checkboxes booleans. */
export type FieldValues = Record<string, string | boolean>;

/** Secret edits made in a form: a string sets the secret, null clears it,
 * and an absent key leaves the stored secret untouched. */
export type SecretEdits = Record<string, string | null>;

function toControlValue(field: FieldSpec, value: Json | undefined): string | boolean {
  if (field.type === "boolean") return value === true || value === "true";
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : typeof value === "object" ? JSON.stringify(value) : String(value);
}

/** Starting form values: the stored value when there is one, else the field's default. */
export function initialValues(fields: FieldSpec[], existing: JsonObject = {}): FieldValues {
  const values: FieldValues = {};
  for (const field of fields) {
    const stored = existing[field.name];
    values[field.name] = toControlValue(field, stored === undefined ? field.default : stored);
  }
  return values;
}

/** Convert form values to a JSON object. Empty fields are left out; number
 * fields become numbers unless they hold something non-numeric such as a
 * `{{ template }}`, which is kept as text. */
export function collectValues(fields: FieldSpec[], values: FieldValues): JsonObject {
  const out: JsonObject = {};
  for (const field of fields) {
    const value = values[field.name];
    if (field.type === "boolean") {
      if (value === true || field.default === true) out[field.name] = value === true;
      continue;
    }
    if (typeof value !== "string" || value.trim() === "") continue;
    if (field.type === "number" && /^-?\d+(\.\d+)?$/.test(value.trim())) {
      out[field.name] = Number(value.trim());
    } else {
      out[field.name] = value;
    }
  }
  return out;
}

/** Keys of `existing` that no field describes, so a form can keep them intact. */
export function extraValues(fields: FieldSpec[], existing: JsonObject): JsonObject {
  const known = new Set(fields.map((field) => field.name));
  return Object.fromEntries(Object.entries(existing).filter(([key]) => !known.has(key)));
}

/** Labels of required fields that are still empty. A secret that is already
 * stored (and not being cleared) counts as filled. */
export function missingRequired(
  fields: FieldSpec[],
  values: FieldValues,
  secretEdits: SecretEdits = {},
  storedSecrets: string[] = [],
): string[] {
  const missing: string[] = [];
  for (const field of fields) {
    if (!field.required || field.type === "boolean") continue;
    if (field.secret) {
      const edit = secretEdits[field.name];
      const filled = edit === undefined ? storedSecrets.includes(field.name) : Boolean(edit);
      if (!filled) missing.push(field.label);
    } else {
      const value = values[field.name];
      if (typeof value !== "string" || value.trim() === "") missing.push(field.label);
    }
  }
  return missing;
}

/** Split a connection form into the API's `config` and `secrets`. Only secrets
 * the user actually changed are included, so stored ones are never overwritten
 * with blanks. */
export function buildConnectionPayload(
  fields: FieldSpec[],
  values: FieldValues,
  secretEdits: SecretEdits,
): { config: JsonObject; secrets?: Record<string, string | null> } {
  const config = collectValues(
    fields.filter((field) => !field.secret),
    values,
  );
  const secrets: Record<string, string | null> = {};
  for (const field of fields) {
    if (!field.secret) continue;
    const edit = secretEdits[field.name];
    if (edit === null || (typeof edit === "string" && edit !== "")) secrets[field.name] = edit;
  }
  return Object.keys(secrets).length ? { config, secrets } : { config };
}
