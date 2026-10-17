import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Action, Operator } from "../api/types";
import { mockApi } from "../test/helpers";
import { BASE, renderInWorkspace } from "../test/render";
import { OperatorsPage } from "./OperatorsPage";

const action = (id: string, name: string, connector: string, operation: string): Action => ({
  id,
  name,
  description: "",
  connection_id: "c1",
  connection_name: "conn",
  connector,
  operation,
  params: {},
  created_at: "2026-10-01T00:00:00.000Z",
  updated_at: "2026-10-01T00:00:00.000Z",
});

const ACTIONS = [
  action("a1", "Find open bugs", "jira", "search_issues"),
  action("a2", "Post to #eng", "slack", "post_message"),
];

const OPERATOR: Operator = {
  id: "op1",
  name: "Weekly digest",
  description: "Bugs to Slack",
  enabled: true,
  tasks: [
    { key: "find", action_id: "a1", params: {}, continue_on_error: false },
    { key: "post", action_id: "a2", params: { text: "{{ tasks.find.output.total }}" }, continue_on_error: false },
  ],
  created_at: "2026-10-01T00:00:00.000Z",
  updated_at: "2026-10-01T00:00:00.000Z",
};

function routes(operators: Operator[] = []) {
  return {
    [`GET ${BASE}/operators`]: { body: operators },
    [`GET ${BASE}/actions`]: { body: ACTIONS },
    [`GET ${BASE}/schedules`]: {
      body: operators.length
        ? [
            {
              id: "s1",
              operator_id: "op1",
              operator_name: "Weekly digest",
              cron: "0 9 * * 1",
              timezone: "UTC",
              enabled: true,
              input: {},
              next_run_at: null,
              last_run_at: null,
              created_at: "",
              updated_at: "",
            },
          ]
        : [],
    },
  };
}

const taskKeys = () =>
  screen
    .getAllByRole("listitem")
    .filter((item) => item.getAttribute("aria-label")?.startsWith("Task "))
    .map((item) => (within(item).getByLabelText("Key") as HTMLInputElement).value);

describe("operator task builder", () => {
  it("adds, edits, reorders and removes tasks, then saves them in order", async () => {
    const api = mockApi({ ...routes(), [`POST ${BASE}/operators`]: { status: 201, body: OPERATOR } });
    renderInWorkspace(<OperatorsPage />);
    await screen.findByText("No operators yet");
    fireEvent.click(screen.getAllByRole("button", { name: "New operator" })[0]!);
    const dialog = within(screen.getByRole("dialog"));

    fireEvent.change(dialog.getByLabelText(/^Name/), { target: { value: "Weekly digest" } });
    fireEvent.click(dialog.getByRole("button", { name: "Add task" }));
    fireEvent.click(dialog.getByRole("button", { name: "Add task" }));
    fireEvent.click(dialog.getByRole("button", { name: "Add task" }));
    expect(taskKeys()).toEqual(["task_1", "task_2", "task_3"]);

    const task = (n: number) => within(dialog.getByRole("listitem", { name: `Task ${n}` }));
    fireEvent.change(task(1).getByLabelText("Key"), { target: { value: "post" } });
    fireEvent.change(task(1).getByLabelText("Action"), { target: { value: "a2" } });
    fireEvent.change(task(1).getByLabelText("Param overrides"), {
      target: { value: '{"text": "{{ tasks.find.output.total }}"}' },
    });
    fireEvent.change(task(2).getByLabelText("Key"), { target: { value: "find" } });
    fireEvent.click(task(2).getByLabelText(/Continue on error/));

    // Put "find" first, drop the unused third task.
    fireEvent.click(dialog.getByRole("button", { name: "Move task 2 up" }));
    expect(taskKeys()).toEqual(["find", "post", "task_3"]);
    fireEvent.click(dialog.getByRole("button", { name: "Remove task 3" }));
    expect(taskKeys()).toEqual(["find", "post"]);
    expect((dialog.getByRole("button", { name: "Move task 1 up" }) as HTMLButtonElement).disabled).toBe(true);
    expect((dialog.getByRole("button", { name: "Move task 2 down" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(dialog.getByRole("button", { name: "Create operator" }));
    await waitFor(() => expect(api.find("POST", `${BASE}/operators`)).toHaveLength(1));
    expect(api.find("POST", `${BASE}/operators`)[0]!.body).toEqual({
      name: "Weekly digest",
      description: "",
      enabled: true,
      tasks: [
        { key: "find", action_id: "a1", params: {}, continue_on_error: true },
        {
          key: "post",
          action_id: "a2",
          params: { text: "{{ tasks.find.output.total }}" },
          continue_on_error: false,
        },
      ],
    });
  });

  it("refuses to save duplicate keys or invalid override JSON", async () => {
    const api = mockApi(routes());
    renderInWorkspace(<OperatorsPage />);
    await screen.findByText("No operators yet");
    fireEvent.click(screen.getAllByRole("button", { name: "New operator" })[0]!);
    const dialog = within(screen.getByRole("dialog"));

    fireEvent.change(dialog.getByLabelText(/^Name/), { target: { value: "Broken" } });
    fireEvent.click(dialog.getByRole("button", { name: "Add task" }));
    fireEvent.click(dialog.getByRole("button", { name: "Add task" }));
    const task = (n: number) => within(dialog.getByRole("listitem", { name: `Task ${n}` }));
    fireEvent.change(task(2).getByLabelText("Key"), { target: { value: "task_1" } });
    fireEvent.change(task(2).getByLabelText("Param overrides"), { target: { value: "{oops" } });

    fireEvent.click(dialog.getByRole("button", { name: "Create operator" }));

    expect(await dialog.findByText("Fix the highlighted tasks before saving.")).toBeTruthy();
    expect(task(1).getByText('Key "task_1" is used more than once.')).toBeTruthy();
    expect(task(2).getByText(/Param overrides:/)).toBeTruthy();
    expect(api.find("POST", `${BASE}/operators`)).toHaveLength(0);
  });

  it("lists operators with their tasks and schedules, and toggles enabled", async () => {
    const api = mockApi({
      ...routes([OPERATOR]),
      [`PATCH ${BASE}/operators/op1`]: { body: { ...OPERATOR, enabled: false } },
    });
    renderInWorkspace(<OperatorsPage />);

    expect(await screen.findByRole("heading", { name: "Weekly digest" })).toBeTruthy();
    expect(screen.getByText("Find open bugs")).toBeTruthy();
    expect(screen.getByText(/At 09:00 on Monday/)).toBeTruthy();

    const toggle = screen.getByRole("switch", { name: "Weekly digest enabled" });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(toggle);
    await waitFor(() => expect(api.find("PATCH", `${BASE}/operators/op1`)).toHaveLength(1));
    expect(api.find("PATCH", `${BASE}/operators/op1`)[0]!.body).toEqual({ enabled: false });
  });

  it("loads an existing operator's tasks into the builder", async () => {
    mockApi(routes([OPERATOR]));
    renderInWorkspace(<OperatorsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit Weekly digest" }));
    expect(taskKeys()).toEqual(["find", "post"]);
    const second = within(screen.getByRole("listitem", { name: "Task 2" }));
    expect((second.getByLabelText("Action") as HTMLSelectElement).value).toBe("a2");
    expect(JSON.parse((second.getByLabelText("Param overrides") as HTMLTextAreaElement).value)).toEqual({
      text: "{{ tasks.find.output.total }}",
    });
  });
});
