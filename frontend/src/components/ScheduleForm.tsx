import { useMemo, useState, type FormEvent } from "react";
import { errorMessage, type Operator, type Schedule } from "../api";
import { useWorkspace } from "../auth/AuthContext";
import { CRON_PRESETS, describeCron, validateCron } from "../lib/cron";
import { parseJsonObject, prettyJson } from "../lib/json";
import { JsonField } from "./JsonField";
import { Button, Checkbox, ErrorNote, Field, FormActions, Input, Modal, Select } from "./ui";

function timezones(): string[] {
  const intl = Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] };
  try {
    return ["UTC", ...(intl.supportedValuesOf?.("timeZone") ?? [])];
  } catch {
    return ["UTC"];
  }
}

interface Props {
  operators: Operator[];
  schedule?: Schedule;
  /** Preselect (and lock) the operator when creating from an operator's row. */
  operatorId?: string;
  onSaved: (schedule: Schedule) => void;
  onClose: () => void;
}

export function ScheduleForm({ operators, schedule, operatorId, onSaved, onClose }: Props) {
  const { api } = useWorkspace();
  const [operator, setOperator] = useState(
    schedule?.operator_id ?? operatorId ?? operators[0]?.id ?? "",
  );
  const [cron, setCron] = useState(schedule?.cron ?? "0 9 * * 1-5");
  const [timezone, setTimezone] = useState(schedule?.timezone ?? "UTC");
  const [enabled, setEnabled] = useState(schedule?.enabled ?? true);
  const [inputText, setInputText] = useState(
    schedule && Object.keys(schedule.input ?? {}).length ? prettyJson(schedule.input) : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const zones = useMemo(timezones, []);
  const cronError = validateCron(cron);
  const input = parseJsonObject(inputText);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (cronError || !input.ok) return;
    setBusy(true);
    setError(null);
    try {
      const body = { cron: cron.trim(), timezone: timezone.trim() || "UTC", enabled, input: input.value };
      onSaved(
        schedule
          ? await api.schedules.update(schedule.id, body)
          : await api.schedules.create({ operator_id: operator, ...body }),
      );
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={schedule ? "Edit schedule" : "New schedule"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field label="Operator" htmlFor="schedule-operator">
          <Select
            id="schedule-operator"
            value={operator}
            disabled={Boolean(schedule) || Boolean(operatorId)}
            onChange={(event) => setOperator(event.target.value)}
          >
            {operators.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
            {schedule && !operators.some((item) => item.id === schedule.operator_id) && (
              <option value={schedule.operator_id}>{schedule.operator_name}</option>
            )}
          </Select>
        </Field>

        <Field
          label="Cron expression"
          htmlFor="schedule-cron"
          error={cronError}
          help={describeCron(cron) || "minute hour day-of-month month day-of-week"}
        >
          <Input
            id="schedule-cron"
            className="font-mono"
            value={cron}
            spellCheck={false}
            autoComplete="off"
            aria-invalid={cronError ? true : undefined}
            aria-describedby="schedule-cron-help"
            onChange={(event) => setCron(event.target.value)}
          />
        </Field>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Common schedules">
          {CRON_PRESETS.map((preset) => (
            <Button key={preset.cron} size="sm" variant="ghost" onClick={() => setCron(preset.cron)}>
              {preset.label}
            </Button>
          ))}
        </div>

        <Field
          label="Timezone"
          htmlFor="schedule-timezone"
          help="IANA name, such as Europe/Berlin. The cron expression is evaluated in this zone."
        >
          <Input
            id="schedule-timezone"
            list="schedule-timezones"
            value={timezone}
            aria-describedby="schedule-timezone-help"
            onChange={(event) => setTimezone(event.target.value)}
          />
          <datalist id="schedule-timezones">
            {zones.map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
        </Field>

        <JsonField
          id="schedule-input"
          label="Input"
          value={inputText}
          onChange={setInputText}
          rows={3}
          help="Optional JSON object passed to every scheduled run."
        />
        <Checkbox
          label="Enabled"
          description="A disabled schedule keeps its settings but does not fire."
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />

        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="submit"
            variant="primary"
            busy={busy}
            disabled={Boolean(cronError) || !input.ok || !operator}
          >
            {schedule ? "Save changes" : "Create schedule"}
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}
