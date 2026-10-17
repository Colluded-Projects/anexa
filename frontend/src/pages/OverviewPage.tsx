import { Link } from "react-router-dom";
import type { RunStatus } from "../api";
import { useWorkspace } from "../auth/AuthContext";
import { Card, CardHeader, ErrorNote, Loading, PageHeader, StatusBadge } from "../components/ui";
import { useAsync, usePolling } from "../lib/hooks";
import { isActive, RunsTable } from "./RunsPage";

const COUNTS: { key: "connections" | "actions" | "operators" | "schedules" | "agents" | "runs"; label: string; to: string }[] = [
  { key: "connections", label: "Connections", to: "/connections" },
  { key: "actions", label: "Actions", to: "/actions" },
  { key: "operators", label: "Operators", to: "/operators" },
  { key: "schedules", label: "Schedules", to: "/schedules" },
  { key: "agents", label: "Agents", to: "/agents" },
  { key: "runs", label: "Runs", to: "/runs" },
];

const STATUSES: RunStatus[] = ["queued", "running", "succeeded", "failed"];

export function OverviewPage() {
  const { api, workspace } = useWorkspace();
  const summary = useAsync(() => api.summary(), [api]);
  const data = summary.data;
  usePolling(summary.reload, (data?.recent_runs ?? []).some(isActive), 4000);

  const graph = Object.entries(data?.graph ?? {}).sort((a, b) => b[1] - a[1]);
  const graphTotal = graph.reduce((sum, [, count]) => sum + count, 0);
  const isNew = data && data.counts.connections === 0;

  return (
    <>
      <PageHeader title={workspace.name} description="What is configured and what has been running." />
      <ErrorNote message={summary.error} className="mb-4" onRetry={() => void summary.reload()} />
      {summary.loading && <Loading label="Loading overview" />}

      {data && (
        <div className="space-y-6">
          {isNew && (
            <Card className="p-5">
              <h2 className="text-base font-semibold">Get started</h2>
              <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-muted">
                <li>
                  <Link to="/connections" className="text-accent underline">
                    Add a connection
                  </Link>{" "}
                  to Slack, GitHub, Jira or Google.
                </li>
                <li>Create actions for the calls you need, including sync actions that fill the graph.</li>
                <li>Combine actions into an operator and give it a schedule.</li>
              </ol>
            </Card>
          )}

          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {COUNTS.map((item) => (
              <li key={item.key}>
                <Link
                  to={item.to}
                  className="block rounded-lg border border-line bg-surface px-4 py-3 hover:border-line-strong"
                >
                  <div className="text-2xl font-semibold tracking-tight tabular-nums">
                    {data.counts[item.key] ?? 0}
                  </div>
                  <div className="text-xs text-muted">{item.label}</div>
                </Link>
              </li>
            ))}
          </ul>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="Runs by status" />
              <dl className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
                {STATUSES.map((status) => (
                  <div key={status}>
                    <dt>
                      <StatusBadge status={status} />
                    </dt>
                    <dd className="mt-1.5 text-xl font-semibold tabular-nums">
                      {data.runs_by_status[status] ?? 0}
                    </dd>
                  </div>
                ))}
              </dl>
            </Card>

            <Card>
              <CardHeader
                title="Company graph"
                actions={
                  <Link to="/graph" className="text-xs font-medium text-accent underline">
                    Explore
                  </Link>
                }
              />
              {graph.length === 0 ? (
                <p className="p-4 text-sm text-muted">
                  Empty. Run a sync action, or add people, teams and decisions by hand.
                </p>
              ) : (
                <ul className="space-y-2.5 p-4">
                  {graph.map(([label, count]) => (
                    <li key={label} className="flex items-center gap-3 text-sm">
                      <span className="w-24 shrink-0 text-muted">{label}</span>
                      <span className="h-2 flex-1 overflow-hidden rounded-full bg-sunken" aria-hidden="true">
                        <span
                          className="block h-full rounded-full bg-accent"
                          style={{ width: `${graphTotal ? Math.max(3, (count / graphTotal) * 100) : 0}%` }}
                        />
                      </span>
                      <span className="w-10 shrink-0 text-right tabular-nums">{count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold">Recent runs</h2>
              <Link to="/runs" className="text-xs font-medium text-accent underline">
                All runs
              </Link>
            </div>
            {data.recent_runs.length === 0 ? (
              <p className="rounded-lg border border-dashed border-line-strong px-4 py-8 text-center text-sm text-muted">
                Nothing has run yet.
              </p>
            ) : (
              <RunsTable runs={data.recent_runs} />
            )}
          </section>
        </div>
      )}
    </>
  );
}
