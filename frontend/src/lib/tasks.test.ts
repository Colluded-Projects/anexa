import { describe, expect, it } from "vitest";
import type { OperatorTask } from "../api/types";
import { moveTask, nextKey, toDrafts, toTasks, validateTasks, type TaskDraft } from "./tasks";

const draft = (overrides: Partial<TaskDraft> = {}): TaskDraft => ({
  key: "find",
  action_id: "a1",
  paramsText: "",
  continue_on_error: false,
  ...overrides,
});

describe("task drafts", () => {
  it("converts to and from the API shape", () => {
    const tasks: OperatorTask[] = [
      { key: "find", action_id: "a1", params: {}, continue_on_error: false },
      { key: "post", action_id: "a2", params: { text: "{{ tasks.find.output.n }}" }, continue_on_error: true },
    ];
    const drafts = toDrafts(tasks);
    expect(drafts[0]!.paramsText).toBe("");
    expect(JSON.parse(drafts[1]!.paramsText)).toEqual(tasks[1]!.params);
    expect(toTasks(drafts)).toEqual(tasks);
  });

  it("picks an unused key", () => {
    expect(nextKey([])).toBe("task_1");
    expect(nextKey([draft({ key: "task_2" })])).toBe("task_3");
    expect(nextKey([draft({ key: "a" }), draft({ key: "task_3" })])).toBe("task_4");
  });

  it("moves tasks within bounds", () => {
    const list = [draft({ key: "a" }), draft({ key: "b" }), draft({ key: "c" })];
    expect(moveTask(list, 0, 1).map((t) => t.key)).toEqual(["b", "a", "c"]);
    expect(moveTask(list, 2, -1).map((t) => t.key)).toEqual(["a", "c", "b"]);
    expect(moveTask(list, 0, -1)).toBe(list);
    expect(moveTask(list, 2, 1)).toBe(list);
  });
});

describe("validateTasks", () => {
  it("accepts well-formed tasks", () => {
    expect(validateTasks([draft(), draft({ key: "_post2", paramsText: '{"a": 1}' })])).toEqual([[], []]);
  });

  it("flags bad keys, duplicates, missing actions and bad JSON per task", () => {
    const problems = validateTasks([
      draft({ key: "" }),
      draft({ key: "1st" }),
      draft({ key: "has-dash" }),
      draft({ key: "dup" }),
      draft({ key: "dup", action_id: "" }),
      draft({ key: "ok", paramsText: "[1, 2]" }),
    ]);
    expect(problems[0]).toEqual(["Key is required."]);
    expect(problems[1]![0]).toMatch(/cannot start with a digit/);
    expect(problems[2]![0]).toMatch(/letters, digits and underscores/);
    expect(problems[3]).toEqual(['Key "dup" is used more than once.']);
    expect(problems[4]).toEqual(['Key "dup" is used more than once.', "Choose an action."]);
    expect(problems[5]![0]).toMatch(/Param overrides: Must be a JSON object/);
  });
});
