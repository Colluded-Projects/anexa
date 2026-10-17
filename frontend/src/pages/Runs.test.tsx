import { act, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Run } from "../api/types";
import { usePolling } from "../lib/hooks";
import { mockApi } from "../test/helpers";
import { BASE, renderInWorkspace } from "../test/render";
import { RunDetailPage } from "./RunDetailPage";
import { RunsPage } from "./RunsPage";

function run(overrides: Partial<Run> = {}): Run {
  return {
    id: "r1",
    kind: "operator",
    target_id: "op1",
    target_name: "Weekly digest",
    status: "running",
    trigger: "manual",
    triggered_by: "u1",
    input: { project: "PLAT" },
    output: null,
    error: null,
    tasks: [
      {
        key: "find",
        action_id: "a1",
        action_name: "Find open bugs",
        status: "running",
        output: null,
        error: null,
        started_at: "2026-10-13T10:00:00.000Z",
        finished_at: null,
      },
      {
        key: "post",
        action_id: "a2",
        action_name: "Post to #eng",
        status: "pending",
        output: null,
        error: null,
        started_at: null,
        finished_at: null,
      },
    ],
    created_at: "2026-10-13T10:00:00.000Z",
    started_at: "2026-10-13T10:00:00.000Z",
    finished_at: null,
    ...overrides,
  };
}

const FAILED = run({
  status: "failed",
  error: "task post failed",
  finished_at: "2026-10-13T10:00:03.500Z",
  output: { find: { total: 3 } },
  tasks: [
    { ...run().tasks[0]!, status: "succeeded", output: { total: 3 }, finished_at: "2026-10-13T10:00:01.200Z" },
    {
      ...run().tasks[1]!,
      status: "failed",
      error: "slack: channel_not_found",
      started_at: "2026-10-13T10:00:01.200Z",
      finished_at: "2026-10-13T10:00:03.500Z",
    },
  ],
});

/** Let pending promises (fetch → state update) settle under fake timers. */
const flush = () => act(async () => void (await vi.advanceTimersByTimeAsync(0)));
const advance = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("usePolling", () => {
  it("ticks only while active and stops on unmount", () => {
    const tick = vi.fn();
    const { rerender, unmount } = renderHook(({ active }) => usePolling(tick, active, 1000), {
      initialProps: { active: false },
    });
    vi.advanceTimersByTime(3000);
    expect(tick).not.toHaveBeenCalled();

    rerender({ active: true });
    vi.advanceTimersByTime(2500);
    expect(tick).toHaveBeenCalledTimes(2);

    rerender({ active: false });
    vi.advanceTimersByTime(3000);
    expect(tick).toHaveBeenCalledTimes(2);

    rerender({ active: true });
    unmount();
    vi.advanceTimersByTime(3000);
    expect(tick).toHaveBeenCalledTimes(2);
  });
});

describe("RunDetailPage", () => {
  it("polls a running run until it finishes, then stops", async () => {
    const responses = [run(), run(), FAILED];
    const api = mockApi({
      [`GET ${BASE}/runs/r1`]: () => ({ body: responses.shift() ?? FAILED }),
    });
    renderInWorkspace(<RunDetailPage />, { route: "/runs/r1", path: "/runs/:runId" });
    await flush();

    expect(screen.getByRole("heading", { name: "Weekly digest" })).toBeTruthy();
    expect(screen.getByText("Updating")).toBeTruthy();
    expect(api.calls).toHaveLength(1);

    await advance(2000);
    expect(api.calls).toHaveLength(2);
    expect(screen.getByText("Updating")).toBeTruthy();

    await advance(2000);
    expect(api.calls).toHaveLength(3);
    expect(screen.queryByText("Updating")).toBeNull();
    // Per-task status, error, output and timing.
    expect(screen.getByText("slack: channel_not_found")).toBeTruthy();
    expect(screen.getByText("task post failed")).toBeTruthy();
    expect(screen.getByLabelText("Output of find").textContent).toContain('"total": 3');
    expect(screen.getByText("1.2 s")).toBeTruthy();
    expect(screen.getByText("2.3 s")).toBeTruthy();

    await advance(10_000);
    expect(api.calls).toHaveLength(3);
  });

  it("does not poll a run that is already finished", async () => {
    const api = mockApi({ [`GET ${BASE}/runs/r1`]: { body: FAILED } });
    renderInWorkspace(<RunDetailPage />, { route: "/runs/r1", path: "/runs/:runId" });
    await flush();
    await advance(10_000);
    expect(api.calls).toHaveLength(1);
  });

  it("shows a missing run as an error", async () => {
    mockApi({ [`GET ${BASE}/runs/nope`]: { status: 404, body: { detail: "Run not found" } } });
    renderInWorkspace(<RunDetailPage />, { route: "/runs/nope", path: "/runs/:runId" });
    await flush();
    expect(screen.getByRole("alert").textContent).toContain("Run not found");
  });
});

describe("RunsPage", () => {
  it("polls while any run is queued or running and sends the filters", async () => {
    const responses = [[run({ status: "queued", tasks: [] })], [run({ status: "succeeded" })]];
    const api = mockApi({
      [`GET ${BASE}/runs`]: () => ({ body: responses.shift() ?? [] }),
    });
    renderInWorkspace(<RunsPage />, { route: "/runs", path: "/runs" });
    await flush();

    expect(api.calls[0]!.url).toBe(`${BASE}/runs?limit=100`);
    expect(screen.getByText(/Updating while runs are in progress/)).toBeTruthy();

    await advance(3000);
    expect(api.calls).toHaveLength(2);
    expect(screen.queryByText(/Updating while runs are in progress/)).toBeNull();

    await advance(9000);
    expect(api.calls).toHaveLength(2);
  });
});
