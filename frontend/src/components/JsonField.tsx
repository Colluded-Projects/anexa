import type { ReactNode } from "react";
import { parseJsonObject } from "../lib/json";
import { Field, Textarea } from "./ui";

/** A textarea that must hold a JSON object; shows the parse error inline. */
export function JsonField({
  id,
  label,
  value,
  onChange,
  help,
  rows = 5,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  help?: ReactNode;
  rows?: number;
}) {
  const parsed = parseJsonObject(value);
  return (
    <Field label={label} htmlFor={id} help={help} error={parsed.ok ? null : parsed.error}>
      <Textarea
        id={id}
        mono
        rows={rows}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={parsed.ok ? undefined : true}
        aria-describedby={`${id}-help`}
        placeholder="{}"
      />
    </Field>
  );
}

export function TemplateHint() {
  return (
    <details className="rounded-md border border-line bg-sunken px-3 py-2 text-xs text-muted">
      <summary className="font-medium text-ink">Using templates in values</summary>
      <div className="mt-2 space-y-1.5">
        <p>
          Any text value can contain <code className="font-mono">{"{{ expression }}"}</code>, filled in
          when the action runs:
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            <code className="font-mono">{"{{ input.channel }}"}</code> — a value from the run's input
          </li>
          <li>
            <code className="font-mono">{"{{ tasks.find.output.issues.0.key }}"}</code> — output of an
            earlier task in the same operator
          </li>
          <li>
            <code className="font-mono">{"{{ run.id }}"}</code>,{" "}
            <code className="font-mono">{"{{ run.started_at }}"}</code>
          </li>
        </ul>
        <p>
          A value that is exactly one expression keeps its type (list, number, object). An expression
          that cannot be resolved fails the task.
        </p>
      </div>
    </details>
  );
}
