import { useState } from "react";
import { errorMessage, type Schedule } from "../api";
import { useWorkspace } from "../auth/AuthContext";
import { ScheduleForm } from "../components/ScheduleForm";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorNote,
  Loading,
  PageHeader,
  Table,
  Td,
  Toggle,
} from "../components/ui";
import { describeCron } from "../lib/cron";
import { formatDateTime, formatRelative } from "../lib/format";
import { useAsync } from "../lib/hooks";

export function SchedulesPage() {
  const { api } = useWorkspace();
  const data = useAsync(
    async () => {
      const [schedules, operators] = await Promise.all([api.schedules.list(), api.operators.list()]);
      return { schedules, operators };
    },
    [api],
  );

  const [editing, setEditing] = useState<Schedule | "new" | null>(null);
  const [deleting, setDeleting] = useState<Schedule | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  async function toggle(schedule: Schedule, enabled: boolean) {
    setRowError(null);
    try {
      await api.schedules.update(schedule.id, { enabled });
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
      await api.schedules.remove(deleting.id);
      setDeleting(null);
      await data.reload();
    } catch (cause) {
      setDeleteError(errorMessage(cause));
    } finally {
      setDeleteBusy(false);
    }
  }

  const schedules = data.data?.schedules ?? [];
  const operators = data.data?.operators ?? [];
  const newButton = (
    <Button variant="primary" disabled={operators.length === 0} onClick={() => setEditing("new")}>
      New schedule
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Schedules"
        description="Cron triggers for operators. The Celery beat process fires them; a worker runs the tasks."
        actions={newButton}
      />
      <ErrorNote message={data.error ?? rowError} className="mb-4" onRetry={() => void data.reload()} />

      {data.loading ? (
        <Loading label="Loading schedules" />
      ) : data.data && operators.length === 0 ? (
        <EmptyState title="Create an operator first">
          Schedules trigger operators. Build one under Operators, then schedule it here.
        </EmptyState>
      ) : schedules.length === 0 && !data.error ? (
        <EmptyState title="Nothing is scheduled" action={newButton}>
          Pick an operator and a cron expression to run it automatically.
        </EmptyState>
      ) : (
        <Table
          head={["Operator", "When", "Timezone", "Next run", "Last run", "Enabled", <span className="sr-only">Actions</span>]}
        >
          {schedules.map((schedule) => (
            <tr key={schedule.id}>
              <Td className="font-medium text-ink">{schedule.operator_name}</Td>
              <Td>
                <code className="font-mono text-[13px]">{schedule.cron}</code>
                <div className="text-xs text-muted">{describeCron(schedule.cron)}</div>
              </Td>
              <Td className="text-muted">{schedule.timezone}</Td>
              <Td className="text-muted">
                {schedule.enabled && schedule.next_run_at ? (
                  <span title={formatDateTime(schedule.next_run_at)}>
                    {formatRelative(schedule.next_run_at)}
                  </span>
                ) : (
                  "—"
                )}
              </Td>
              <Td className="text-muted">
                {schedule.last_run_at ? (
                  <span title={formatDateTime(schedule.last_run_at)}>
                    {formatRelative(schedule.last_run_at)}
                  </span>
                ) : (
                  "Never"
                )}
              </Td>
              <Td>
                <Toggle
                  checked={schedule.enabled}
                  onChange={(next) => void toggle(schedule, next)}
                  label={`Schedule for ${schedule.operator_name} enabled`}
                />
              </Td>
              <Td>
                <div className="flex justify-end gap-1.5">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setEditing(schedule)}
                    aria-label={`Edit schedule for ${schedule.operator_name}`}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setDeleteError(null);
                      setDeleting(schedule);
                    }}
                    aria-label={`Delete schedule for ${schedule.operator_name}`}
                  >
                    Delete
                  </Button>
                </div>
              </Td>
            </tr>
          ))}
        </Table>
      )}

      {editing && (
        <ScheduleForm
          operators={operators}
          schedule={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void data.reload();
          }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete this schedule?"
          busy={deleteBusy}
          error={deleteError}
          onCancel={() => setDeleting(null)}
          onConfirm={() => void confirmDelete()}
        >
          {deleting.operator_name} will no longer run on <code className="font-mono">{deleting.cron}</code>.
        </ConfirmDialog>
      )}
    </>
  );
}
