import type { FieldSpec } from "../api/types";
import type { FieldValues, SecretEdits } from "../lib/fields";
import { Badge, Checkbox, Field, Input, Select, Textarea } from "./ui";

interface FieldsFormProps {
  fields: FieldSpec[];
  values: FieldValues;
  onChange: (name: string, value: string | boolean) => void;
  idPrefix: string;
  /** Number fields accept free text so they can hold `{{ templates }}`. */
  allowTemplates?: boolean;
  /** Secret handling; omit when the fields contain no secrets. */
  secretEdits?: SecretEdits;
  storedSecrets?: string[];
  onSecretChange?: (name: string, value: string | null | undefined) => void;
}

/** Renders one control per FieldSpec from the connector catalog. */
export function FieldsForm({
  fields,
  values,
  onChange,
  idPrefix,
  allowTemplates = false,
  secretEdits = {},
  storedSecrets = [],
  onSecretChange,
}: FieldsFormProps) {
  if (fields.length === 0) {
    return <p className="text-sm text-muted">Nothing to configure.</p>;
  }

  return (
    <div className="space-y-4">
      {fields.map((field) => {
        const id = `${idPrefix}-${field.name}`;
        const describedBy = field.help ? `${id}-help` : undefined;

        if (field.type === "boolean") {
          return (
            <Checkbox
              key={field.name}
              label={field.label}
              description={field.help}
              checked={values[field.name] === true}
              onChange={(event) => onChange(field.name, event.target.checked)}
            />
          );
        }

        if (field.secret) {
          const stored = storedSecrets.includes(field.name);
          const edit = secretEdits[field.name];
          const clearing = edit === null;
          const common = {
            id,
            value: typeof edit === "string" ? edit : "",
            required: field.required && !stored,
            disabled: clearing,
            "aria-describedby": describedBy,
            placeholder: clearing
              ? "Will be removed when you save"
              : stored
                ? "Saved — leave blank to keep the current value"
                : field.placeholder,
          };
          return (
            <Field
              key={field.name}
              label={field.label}
              htmlFor={id}
              help={field.help}
              required={field.required}
            >
              <div className="flex items-start gap-2">
                {field.type === "text" ? (
                  <Textarea
                    {...common}
                    mono
                    rows={4}
                    onChange={(event) => onSecretChange?.(field.name, event.target.value || undefined)}
                  />
                ) : (
                  <Input
                    {...common}
                    type="password"
                    autoComplete="new-password"
                    onChange={(event) => onSecretChange?.(field.name, event.target.value || undefined)}
                  />
                )}
                {stored && !clearing && (
                  <span className="mt-1.5 shrink-0">
                    <Badge tone="ok">set</Badge>
                  </span>
                )}
              </div>
              {stored && !field.required && (
                <button
                  type="button"
                  className="text-xs font-medium text-muted underline hover:text-ink"
                  onClick={() => onSecretChange?.(field.name, clearing ? undefined : null)}
                >
                  {clearing ? `Keep stored ${field.label}` : `Remove stored ${field.label}`}
                </button>
              )}
            </Field>
          );
        }

        const value = typeof values[field.name] === "string" ? (values[field.name] as string) : "";
        return (
          <Field
            key={field.name}
            label={field.label}
            htmlFor={id}
            help={field.help}
            required={field.required}
          >
            {field.type === "select" ? (
              <Select
                id={id}
                value={value}
                required={field.required}
                aria-describedby={describedBy}
                onChange={(event) => onChange(field.name, event.target.value)}
              >
                <option value="">{field.required ? "Choose…" : "None"}</option>
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            ) : field.type === "text" ? (
              <Textarea
                id={id}
                rows={4}
                value={value}
                required={field.required}
                placeholder={field.placeholder}
                aria-describedby={describedBy}
                onChange={(event) => onChange(field.name, event.target.value)}
              />
            ) : (
              <Input
                id={id}
                type={field.type === "number" && !allowTemplates ? "number" : "text"}
                inputMode={field.type === "number" ? "decimal" : undefined}
                value={value}
                required={field.required}
                placeholder={field.placeholder}
                aria-describedby={describedBy}
                onChange={(event) => onChange(field.name, event.target.value)}
              />
            )}
          </Field>
        );
      })}
    </div>
  );
}
