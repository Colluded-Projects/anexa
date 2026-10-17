import type { Action } from "../api/types";
import { moveTask, nextKey, validateTasks, type TaskDraft } from "../lib/tasks";
import { Button, Checkbox, Field, Input, Select, Textarea } from "./ui";

interface TaskBuilderProps {
  tasks: TaskDraft[];
  actions: Action[];
  onChange: (tasks: TaskDraft[]) => void;
  /** Show validation messages (after a save attempt). */
  showErrors?: boolean;
}

/** Ordered list of an operator's tasks: add, reorder, remove and edit. */
export function TaskBuilder({ tasks, actions, onChange, showErrors = false }: TaskBuilderProps) {
  const problems = validateTasks(tasks);

  function patch(index: number, changes: Partial<TaskDraft>) {
    onChange(tasks.map((task, i) => (i === index ? { ...task, ...changes } : task)));
  }

  function add() {
    onChange([
      ...tasks,
      { key: nextKey(tasks), action_id: actions[0]?.id ?? "", paramsText: "", continue_on_error: false },
    ]);
  }

  return (
    <div className="space-y-3">
      {tasks.length === 0 && (
        <p className="rounded-md border border-dashed border-line-strong px-4 py-6 text-center text-sm text-muted">
          No tasks yet. Tasks run top to bottom; each one runs an action.
        </p>
      )}

      <ol className="space-y-3">
        {tasks.map((task, index) => {
          const id = `task-${index}`;
          const errors = showErrors ? (problems[index] ?? []) : [];
          return (
            <li
              key={index}
              aria-label={`Task ${index + 1}`}
              className="rounded-md border border-line bg-sunken/50 p-4"
            >
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="text-xs font-semibold tracking-wide text-muted uppercase">
                  Step {index + 1}
                </span>
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={index === 0}
                    onClick={() => onChange(moveTask(tasks, index, -1))}
                    aria-label={`Move task ${index + 1} up`}
                  >
                    ↑
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={index === tasks.length - 1}
                    onClick={() => onChange(moveTask(tasks, index, 1))}
                    aria-label={`Move task ${index + 1} down`}
                  >
                    ↓
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => onChange(tasks.filter((_, i) => i !== index))}
                    aria-label={`Remove task ${index + 1}`}
                  >
                    Remove
                  </Button>
                </div>
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field
                  label="Key"
                  htmlFor={`${id}-key`}
                  help={
                    <>
                      Later tasks read this one as{" "}
                      <code className="font-mono">{`{{ tasks.${task.key || "key"}.output }}`}</code>
                    </>
                  }
                >
                  <Input
                    id={`${id}-key`}
                    value={task.key}
                    aria-describedby={`${id}-key-help`}
                    onChange={(event) => patch(index, { key: event.target.value })}
                  />
                </Field>
                <Field label="Action" htmlFor={`${id}-action`}>
                  <Select
                    id={`${id}-action`}
                    value={task.action_id}
                    onChange={(event) => patch(index, { action_id: event.target.value })}
                  >
                    <option value="">Choose an action…</option>
                    {actions.map((action) => (
                      <option key={action.id} value={action.id}>
                        {action.name} ({action.connector}.{action.operation})
                      </option>
                    ))}
                    {task.action_id && !actions.some((action) => action.id === task.action_id) && (
                      <option value={task.action_id}>Missing action ({task.action_id})</option>
                    )}
                  </Select>
                </Field>
              </div>

              <div className="mt-4 space-y-3">
                <Field
                  label="Param overrides"
                  htmlFor={`${id}-params`}
                  help="Optional JSON object merged over the action's own params for this step."
                >
                  <Textarea
                    id={`${id}-params`}
                    mono
                    rows={3}
                    value={task.paramsText}
                    placeholder='{"text": "{{ tasks.find.output.summary }}"}'
                    aria-describedby={`${id}-params-help`}
                    onChange={(event) => patch(index, { paramsText: event.target.value })}
                  />
                </Field>
                <Checkbox
                  label="Continue on error"
                  description="Keep running later tasks if this one fails."
                  checked={task.continue_on_error}
                  onChange={(event) => patch(index, { continue_on_error: event.target.checked })}
                />
              </div>

              {errors.length > 0 && (
                <ul role="alert" className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-danger">
                  {errors.map((message) => (
                    <li key={message}>{message}</li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>

      <Button onClick={add} disabled={actions.length === 0}>
        Add task
      </Button>
      {actions.length === 0 && (
        <p className="text-xs text-muted">Create an action first; tasks run actions.</p>
      )}
    </div>
  );
}
