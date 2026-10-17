import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { useWorkspace } from "../auth/AuthContext";
import {
  Badge,
  Card,
  CardHeader,
  CodeBlock,
  ErrorNote,
  Loading,
  Spinner,
  StatusBadge,
} from "../components/ui";
import { formatDateTime, formatDuration } from "../lib/format";
import { useAsync, usePolling } from "../lib/hooks";
import { prettyJson } from "../lib/json";
import { isActive } from "./RunsPage";

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{children}</dd>
    </div>
  );
}

export function RunDetailPage() {
  const { runId = "" } = useParams();
  const { api } = useWorkspace();
  const state = useAsync(() => api.runs.get(runId), [api, runId]);
  const run = state.data;
  const live = run ? isActive(run) : false;
  usePolling(state.reload, live, 2000);

  return (
    <>
      <p className="mb-3 text-sm">
        <Link to="/runs" className="text-muted underline hover:text-ink">
          ← All runs
        </Link>
      </p>

      {state.loading && <Loading label="Loading run" />}
      <ErrorNote message={state.error} className="mb-4" onRetry={() => void state.reload()} />

      {run && (
        <div className="space-y-5">
          <header className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-semibold tracking-tight">{run.target_name || run.target_id}</h1>
            <StatusBadge status={run.status} />
            {live && (
              <span className="flex items-center gap-2 text-xs text-muted" role="status">
                <Spinner small /> Updating
              </span>
            )}
          </header>

          <Card className="p-4">
            <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
              <Fact label="Kind">{run.kind}</Fact>
              <Fact label="Trigger">
                <Badge>{run.trigger}</Badge>
              </Fact>
              <Fact label="Queued">{formatDateTime(run.created_at)}</Fact>
              <Fact label="Started">{formatDateTime(run.started_at)}</Fact>
              <Fact label="Finished">{formatDateTime(run.finished_at)}</Fact>
              <Fact label="Duration">{formatDuration(run.started_at, run.finished_at)}</Fact>
            </dl>
            <p className="mt-4 font-mono text-xs break-all text-muted">Run {run.id}</p>
          </Card>

          {run.error && <ErrorNote message={run.error} />}

          <Card>
            <CardHeader title={run.kind === "operator" ? "Tasks" : "Task"} />
            {run.tasks.length === 0 ? (
              <p className="px-4 py-6 text-sm text-muted">
                {live ? "Waiting for a worker to pick this run up." : "This run recorded no tasks."}
              </p>
            ) : (
              <ol className="divide-y divide-line">
                {run.tasks.map((task) => (
                  <li key={task.key} className="px-4 py-4">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="font-mono text-sm font-medium text-ink">{task.key}</span>
                      <StatusBadge status={task.status} />
                      <span className="text-sm text-muted">{task.action_name || task.action_id}</span>
                      <span className="ml-auto text-xs text-muted">
                        {formatDuration(task.started_at, task.finished_at)}
                      </span>
                    </div>
                    {task.error && (
                      <p className="mt-2 rounded-md bg-danger-soft px-3 py-2 text-sm break-words text-danger">
                        {task.error}
                      </p>
                    )}
                    {task.output && (
                      <details className="mt-2" open={run.tasks.length === 1}>
                        <summary className="text-xs font-medium text-muted hover:text-ink">Output</summary>
                        <div className="mt-2">
                          <CodeBlock label={`Output of ${task.key}`}>{prettyJson(task.output)}</CodeBlock>
                        </div>
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            )}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card>
              <CardHeader title="Input" />
              <div className="p-4">
                <CodeBlock label="Run input">{prettyJson(run.input)}</CodeBlock>
              </div>
            </Card>
            <Card>
              <CardHeader title="Output" />
              <div className="p-4">
                {run.output ? (
                  <CodeBlock label="Run output">{prettyJson(run.output)}</CodeBlock>
                ) : (
                  <p className="text-sm text-muted">{live ? "Not finished yet." : "No output."}</p>
                )}
              </div>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
