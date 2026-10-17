import { useState } from "react";
import { Link } from "react-router-dom";
import type { Run, RunKind, RunStatus } from "../api";
import { useWorkspace } from "../auth/AuthContext";
import {
  Badge,
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  Select,
  Spinner,
  StatusBadge,
  Table,
  Td,
} from "../components/ui";
import { formatDateTime, formatDuration, formatRelative } from "../lib/format";
import { useAsync, usePolling } from "../lib/hooks";

export const isActive = (run: Pick<Run, "status">) =>
  run.status === "queued" || run.status === "running";

export function RunsTable({ runs }: { runs: Run[] }) {
  return (
    <Table head={["Target", "Status", "Trigger", "Started", "Duration"]}>
      {runs.map((run) => (
        <tr key={run.id}>
          <Td>
            <Link to={`/runs/${run.id}`} className="font-medium text-accent underline">
              {run.target_name || run.target_id}
            </Link>
            <div className="text-xs text-muted">{run.kind}</div>
          </Td>
          <Td>
            <StatusBadge status={run.status} />
          </Td>
          <Td>
            <Badge>{run.trigger}</Badge>
          </Td>
          <Td className="text-muted">
            <span title={formatDateTime(run.started_at ?? run.created_at)}>
              {formatRelative(run.started_at ?? run.created_at)}
            </span>
          </Td>
          <Td className="text-muted">{formatDuration(run.started_at, run.finished_at)}</Td>
        </tr>
      ))}
    </Table>
  );
}

export function RunsPage() {
  const { api } = useWorkspace();
  const [kind, setKind] = useState<RunKind | "">("");
  const [status, setStatus] = useState<RunStatus | "">("");

  const runs = useAsync(
    () => api.runs.list({ kind: kind || undefined, status: status || undefined, limit: 100 }),
    [api, kind, status],
  );
  const live = (runs.data ?? []).some(isActive);
  usePolling(runs.reload, live, 3000);

  const filtered = Boolean(kind || status);

  return (
    <>
      <PageHeader
        title="Runs"
        description="Every execution of an action or operator, newest first."
        actions={
          live ? (
            <span className="flex items-center gap-2 text-xs text-muted" role="status">
              <Spinner small /> Updating while runs are in progress
            </span>
          ) : undefined
        }
      />

      <div className="mb-4 flex flex-wrap gap-3">
        <div>
          <label htmlFor="runs-kind" className="mb-1 block text-xs font-medium text-muted">
            Kind
          </label>
          <Select
            id="runs-kind"
            className="w-40!"
            value={kind}
            onChange={(event) => setKind(event.target.value as RunKind | "")}
          >
            <option value="">All kinds</option>
            <option value="action">Action</option>
            <option value="operator">Operator</option>
          </Select>
        </div>
        <div>
          <label htmlFor="runs-status" className="mb-1 block text-xs font-medium text-muted">
            Status
          </label>
          <Select
            id="runs-status"
            className="w-40!"
            value={status}
            onChange={(event) => setStatus(event.target.value as RunStatus | "")}
          >
            <option value="">All statuses</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
          </Select>
        </div>
      </div>

      <ErrorNote message={runs.error} className="mb-4" onRetry={() => void runs.reload()} />
      {runs.loading ? (
        <Loading label="Loading runs" />
      ) : (runs.data ?? []).length === 0 && !runs.error ? (
        <EmptyState title={filtered ? "No runs match these filters" : "Nothing has run yet"}>
          {filtered
            ? "Try clearing a filter."
            : "Run an action or operator, or wait for a schedule to fire."}
        </EmptyState>
      ) : (
        <RunsTable runs={runs.data ?? []} />
      )}
    </>
  );
}
