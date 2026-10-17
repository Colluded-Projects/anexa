import { useState, type FormEvent } from "react";
import { errorMessage, type Action, type Operator, type Schedule } from "../api";
import { useWorkspace } from "../auth/AuthContext";
import { TemplateHint } from "../components/JsonField";
import { RunDialog } from "../components/RunDialog";
import { ScheduleForm } from "../components/ScheduleForm";
import { TaskBuilder } from "../components/TaskBuilder";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorNote,
  Field,
  FormActions,
  Input,
  Loading,
  Modal,
  PageHeader,
  Toggle,
} from "../components/ui";
import { describeCron } from "../lib/cron";
import { formatRelative } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { toDrafts, toTasks, validateTasks, type TaskDraft } from "../lib/tasks";

interface FormProps {
  actions: Action[];
  operator?: Operator;
  onSaved: (operator: Operator) => void;
  onClose: () => void;
}

export function OperatorForm({ actions, operator, onSaved, onClose }: FormProps) {
  const { api } = useWorkspace();
  const [name, setName] = useState(operator?.name ?? "");
  const [description, setDescription] = useState(operator?.description ?? "");
  const [enabled, setEnabled] = useState(operator?.enabled ?? true);
  const [tasks, setTasks] = useState<TaskDraft[]>(() => toDrafts(operator?.tasks ?? []));
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (validateTasks(tasks).some((problems) => problems.length > 0)) {
      setShowErrors(true);
      setError("Fix the highlighted tasks before saving.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        description: description.trim(),
        enabled,
        tasks: toTasks(tasks),
      };
      onSaved(
        operator ? await api.operators.update(operator.id, body) : await api.operators.create(body),
      );
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={operator ? `Edit ${operator.name}` : "New operator"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-5" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="operator-name" required>
            <Input
              id="operator-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Weekly ticket digest"
              required
            />
          </Field>
          <Field label="Description" htmlFor="operator-description">
            <Input
              id="operator-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
        </div>
        <Checkbox
          label="Enabled"
          description="Schedules only fire for enabled operators."
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />

        <div>
          <h3 className="mb-1 text-sm font-semibold">Tasks</h3>
          <p className="mb-3 text-xs text-muted">
            Run in order. A failed task fails the run and skips the rest unless it continues on error.
          </p>
          <TaskBuilder tasks={tasks} actions={actions} onChange={setTasks} showErrors={showErrors} />
        </div>
        <TemplateHint />

        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>
            {operator ? "Save changes" : "Create operator"}
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}

export function OperatorsPage() {
  const { api } = useWorkspace();
  const data = useAsync(
    async () => {
      const [operators, actions, schedules] = await Promise.all([
        api.operators.list(),
        api.actions.list(),
        api.schedules.list(),
      ]);
      return { operators, actions, schedules };
    },
    [api],
  );

  const [editing, setEditing] = useState<Operator | "new" | null>(null);
  const [running, setRunning] = useState<Operator | null>(null);
  const [scheduling, setScheduling] = useState<Operator | null>(null);
  const [deleting, setDeleting] = useState<Operator | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  async function toggle(operator: Operator, enabled: boolean) {
    setRowError(null);
    try {
      await api.operators.update(operator.id, { enabled });
      await data.reload();
    } catch (cause) {
      setRowError(errorMessage(cause));
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.operators.remove(deleting.id);
      setDeleting(null);
      await data.reload();
    } catch (cause) {
      setDeleteError(errorMessage(cause));
    } finally {
      setDeleteBusy(false);
    }
  }

  const operators = data.data?.operators ?? [];
  const actions = data.data?.actions ?? [];
  const actionNames = new Map(actions.map((action) => [action.id, action.name]));
  const schedulesFor = (operator: Operator): Schedule[] =>
    (data.data?.schedules ?? []).filter((schedule) => schedule.operator_id === operator.id);

  const newButton = (
    <Button variant="primary" onClick={() => setEditing("new")}>
      New operator
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Operators"
        description="Workflows that run actions as ordered tasks. Run one on demand, on a schedule, or from Claude Code through MCP."
        actions={newButton}
      />
      <ErrorNote message={data.error ?? rowError} className="mb-4" onRetry={() => void data.reload()} />

      {data.loading ? (
        <Loading label="Loading operators" />
      ) : operators.length === 0 && !data.error ? (
        <EmptyState title="No operators yet" action={newButton}>
          An operator strings actions together, passing each task's output to the next.
        </EmptyState>
      ) : (
        <ul className="space-y-3">
          {operators.map((operator) => {
            const schedules = schedulesFor(operator);
            return (
              <li key={operator.id}>
                <Card className="p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-[15px] font-semibold text-ink">{operator.name}</h2>
                        {!operator.enabled && <Badge>disabled</Badge>}
                      </div>
                      {operator.description && (
                        <p className="mt-0.5 text-sm text-muted">{operator.description}</p>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Toggle
                        checked={operator.enabled}
                        onChange={(next) => void toggle(operator, next)}
                        label={`${operator.name} enabled`}
                      />
                      <Button
                        size="sm"
                        onClick={() => setRunning(operator)}
                        aria-label={`Run ${operator.name}`}
                      >
                        Run
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => setEditing(operator)}
                        aria-label={`Edit ${operator.name}`}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setDeleteError(null);
                          setDeleting(operator);
                        }}
                        aria-label={`Delete ${operator.name}`}
                      >
                        Delete
                      </Button>
                    </div>
                  </div>

                  {operator.tasks.length > 0 ? (
                    <ol className="mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1.5 text-xs">
                      {operator.tasks.map((task, index) => (
                        <li key={task.key} className="flex items-center gap-1.5">
                          {index > 0 && (
                            <span className="text-muted" aria-hidden="true">
                              →
                            </span>
                          )}
                          <span className="rounded border border-line bg-sunken px-2 py-1">
                            <span className="font-mono text-muted">{task.key}</span>{" "}
                            <span className="text-ink">
                              {actionNames.get(task.action_id) ?? "missing action"}
                            </span>
                          </span>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <p className="mt-3 text-xs text-muted">No tasks yet. Edit to add some.</p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-3 text-xs text-muted">
                    <span className="font-medium text-ink">Schedules</span>
                    {schedules.length === 0 && <span>None</span>}
                    {schedules.map((schedule) => (
                      <span key={schedule.id}>
                        <code className="font-mono">{schedule.cron}</code>{" "}
                        {describeCron(schedule.cron) && `· ${describeCron(schedule.cron)} `}
                        {schedule.enabled
                          ? `· next ${formatRelative(schedule.next_run_at)}`
                          : "· disabled"}
                      </span>
                    ))}
                    <button
                      type="button"
                      className="font-medium text-accent underline"
                      onClick={() => setScheduling(operator)}
                    >
                      Add schedule
                    </button>
                  </div>
                </Card>
              </li>
            );
          })}
        </ul>
      )}

      {editing && data.data && (
        <OperatorForm
          actions={actions}
          operator={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void data.reload();
          }}
        />
      )}
      {scheduling && (
        <ScheduleForm
          operators={operators}
          operatorId={scheduling.id}
          onClose={() => setScheduling(null)}
          onSaved={() => {
            setScheduling(null);
            void data.reload();
          }}
        />
      )}
      {running && (
        <RunDialog
          title={`Run ${running.name}`}
          start={(input) => api.operators.run(running.id, input)}
          onClose={() => setRunning(null)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={`Delete ${deleting.name}?`}
          busy={deleteBusy}
          error={deleteError}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void confirmDelete()}
        >
          Its schedules are deleted too. Past runs stay in the history.
        </ConfirmDialog>
      )}
    </>
  );
}
