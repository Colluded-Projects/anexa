import type { OperatorTask } from "../api/types";
import { parseJsonObject, prettyJson } from "./json";

/** A task while it is being edited: params are kept as the text the user typed. */
export interface TaskDraft {
  key: string;
  action_id: string;
  paramsText: string;
  continue_on_error: boolean;
}

const KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

export function toDrafts(tasks: OperatorTask[]): TaskDraft[] {
  return tasks.map((task) => ({
    key: task.key,
    action_id: task.action_id,
    paramsText: Object.keys(task.params ?? {}).length ? prettyJson(task.params) : "",
    continue_on_error: task.continue_on_error,
  }));
}

/** Next unused `task_N` key. */
export function nextKey(drafts: TaskDraft[]): string {
  const used = new Set(drafts.map((draft) => draft.key));
  let n = drafts.length + 1;
  while (used.has(`task_${n}`)) n++;
  return `task_${n}`;
}

export function moveTask(drafts: TaskDraft[], index: number, delta: -1 | 1): TaskDraft[] {
  const target = index + delta;
  if (target < 0 || target >= drafts.length) return drafts;
  const next = [...drafts];
  const [moved] = next.splice(index, 1);
  next.splice(target, 0, moved as TaskDraft);
  return next;
}

/** One list of problems per task, in order; an empty list means the task is fine. */
export function validateTasks(drafts: TaskDraft[]): string[][] {
  const counts = new Map<string, number>();
  for (const draft of drafts) counts.set(draft.key, (counts.get(draft.key) ?? 0) + 1);

  return drafts.map((draft) => {
    const problems: string[] = [];
    if (!draft.key) problems.push("Key is required.");
    else if (!KEY_PATTERN.test(draft.key)) {
      problems.push("Key may only use letters, digits and underscores, and cannot start with a digit.");
    } else if ((counts.get(draft.key) ?? 0) > 1) problems.push(`Key "${draft.key}" is used more than once.`);
    if (!draft.action_id) problems.push("Choose an action.");
    const parsed = parseJsonObject(draft.paramsText);
    if (!parsed.ok) problems.push(`Param overrides: ${parsed.error}`);
    return problems;
  });
}

/** Convert drafts to the API shape. Call only after validateTasks reports no problems. */
export function toTasks(drafts: TaskDraft[]): OperatorTask[] {
  return drafts.map((draft) => {
    const parsed = parseJsonObject(draft.paramsText);
    return {
      key: draft.key,
      action_id: draft.action_id,
      params: parsed.ok ? parsed.value : {},
      continue_on_error: draft.continue_on_error,
    };
  });
}
