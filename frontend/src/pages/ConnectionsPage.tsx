import { useMemo, useState, type FormEvent } from "react";
import {
  connectors as connectorsApi,
  errorMessage,
  type Connection,
  type ConnectionTest,
  type ConnectorSpec,
} from "../api";
import { useWorkspace } from "../auth/AuthContext";
import { FieldsForm } from "../components/FieldsForm";
import {
  Button,
  ConfirmDialog,
  EmptyState,
  ErrorNote,
  Field,
  FormActions,
  Input,
  Loading,
  Modal,
  Note,
  PageHeader,
  Select,
  StatusBadge,
  Table,
  Td,
} from "../components/ui";
import {
  buildConnectionPayload,
  initialValues,
  missingRequired,
  type FieldValues,
  type SecretEdits,
} from "../lib/fields";
import { formatRelative } from "../lib/format";
import { useAsync } from "../lib/hooks";

interface FormProps {
  catalog: ConnectorSpec[];
  connection?: Connection;
  onSaved: (connection: Connection) => void;
  onClose: () => void;
}

export function ConnectionForm({ catalog, connection, onSaved, onClose }: FormProps) {
  const { api } = useWorkspace();
  const [connectorKey, setConnectorKey] = useState(connection?.connector ?? catalog[0]?.key ?? "");
  const spec = catalog.find((item) => item.key === connectorKey);
  const fields = useMemo(() => spec?.config_fields ?? [], [spec]);

  const [name, setName] = useState(connection?.name ?? "");
  const [values, setValues] = useState<FieldValues>(() =>
    initialValues(fields, connection?.config),
  );
  const [secretEdits, setSecretEdits] = useState<SecretEdits>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function chooseConnector(key: string) {
    setConnectorKey(key);
    setValues(initialValues(catalog.find((item) => item.key === key)?.config_fields ?? []));
    setSecretEdits({});
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const missing = missingRequired(fields, values, secretEdits, connection?.secret_fields);
    if (missing.length) {
      setError(`Fill in: ${missing.join(", ")}.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const payload = buildConnectionPayload(fields, values, secretEdits);
      const saved = connection
        ? await api.connections.update(connection.id, { name: name.trim(), ...payload })
        : await api.connections.create({ name: name.trim(), connector: connectorKey, ...payload });
      onSaved(saved);
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={connection ? `Edit ${connection.name}` : "New connection"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <Field
          label="Connector"
          htmlFor="connection-connector"
          help={connection ? "The connector cannot be changed after creation." : spec?.description}
        >
          <Select
            id="connection-connector"
            value={connectorKey}
            disabled={Boolean(connection)}
            aria-describedby="connection-connector-help"
            onChange={(event) => chooseConnector(event.target.value)}
          >
            {catalog.map((item) => (
              <option key={item.key} value={item.key}>
                {item.title}
              </option>
            ))}
            {connection && !spec && <option value={connection.connector}>{connection.connector}</option>}
          </Select>
        </Field>
        <Field label="Name" htmlFor="connection-name" required>
          <Input
            id="connection-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Engineering Slack"
            required
          />
        </Field>

        {spec ? (
          <FieldsForm
            key={connectorKey}
            idPrefix="connection-field"
            fields={fields}
            values={values}
            onChange={(field, value) => setValues((current) => ({ ...current, [field]: value }))}
            secretEdits={secretEdits}
            storedSecrets={connection?.secret_fields}
            onSecretChange={(field, value) =>
              setSecretEdits((current) => {
                const next = { ...current };
                if (value === undefined) delete next[field];
                else next[field] = value;
                return next;
              })
            }
          />
        ) : (
          <Note>This connector is not in the server's catalog, so its fields cannot be edited.</Note>
        )}

        {fields.some((field) => field.secret) && (
          <p className="text-xs text-muted">
            Secrets are encrypted on the server and are never sent back to the browser.
          </p>
        )}
        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || !connectorKey}>
            {connection ? "Save changes" : "Create connection"}
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}

export function ConnectionsPage() {
  const { api } = useWorkspace();
  const catalog = useAsync(() => connectorsApi.list(), []);
  const list = useAsync(() => api.connections.list(), [api]);

  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const [deleting, setDeleting] = useState<Connection | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ConnectionTest | { error: string }>>({});

  const titles = useMemo(
    () => Object.fromEntries((catalog.data ?? []).map((item) => [item.key, item.title])),
    [catalog.data],
  );

  async function test(connection: Connection) {
    setTesting(connection.id);
    try {
      const result = await api.connections.test(connection.id);
      setResults((current) => ({ ...current, [connection.id]: result }));
      await list.reload();
    } catch (cause) {
      setResults((current) => ({ ...current, [connection.id]: { error: errorMessage(cause) } }));
    } finally {
      setTesting(null);
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.connections.remove(deleting.id);
      setDeleting(null);
      await list.reload();
    } catch (cause) {
      setDeleteError(errorMessage(cause));
    } finally {
      setDeleteBusy(false);
    }
  }

  const error = list.error ?? catalog.error;
  const rows = list.data ?? [];

  return (
    <>
      <PageHeader
        title="Connections"
        description="Credentials for the systems your company works in. Actions call them; sync operations feed the company graph."
        actions={
          <Button
            variant="primary"
            disabled={!catalog.data?.length}
            onClick={() => setEditing("new")}
          >
            New connection
          </Button>
        }
      />
      <ErrorNote
        message={error}
        className="mb-4"
        onRetry={() => {
          void list.reload();
          void catalog.reload();
        }}
      />

      {list.loading ? (
        <Loading label="Loading connections" />
      ) : rows.length === 0 && !list.error ? (
        <EmptyState
          title="No connections yet"
          action={
            <Button variant="primary" disabled={!catalog.data?.length} onClick={() => setEditing("new")}>
              New connection
            </Button>
          }
        >
          Connect Slack, GitHub, Jira or Google with a token. Everything else builds on a connection.
        </EmptyState>
      ) : (
        <Table head={["Name", "Connector", "Status", "Updated", <span className="sr-only">Actions</span>]}>
          {rows.map((connection) => {
            const result = results[connection.id];
            return (
              <tr key={connection.id}>
                <Td>
                  <div className="font-medium text-ink">{connection.name}</div>
                  {result && (
                    <div
                      role="status"
                      className={`mt-1 text-xs ${"error" in result || !result.ok ? "text-danger" : "text-ok"}`}
                    >
                      {"error" in result
                        ? result.error
                        : `${result.ok ? "Connected" : "Failed"}${result.detail ? `: ${result.detail}` : ""}`}
                    </div>
                  )}
                  {!result && connection.status === "error" && connection.status_detail && (
                    <div className="mt-1 text-xs text-danger">{connection.status_detail}</div>
                  )}
                </Td>
                <Td className="text-muted">{titles[connection.connector] ?? connection.connector}</Td>
                <Td>
                  <StatusBadge status={connection.status} />
                </Td>
                <Td className="text-muted">{formatRelative(connection.updated_at)}</Td>
                <Td>
                  <div className="flex justify-end gap-1.5">
                    <Button
                      size="sm"
                      busy={testing === connection.id}
                      onClick={() => void test(connection)}
                      aria-label={`Test ${connection.name}`}
                    >
                      Test
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setEditing(connection)}
                      aria-label={`Edit ${connection.name}`}
                    >
                      Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setDeleteError(null);
                        setDeleting(connection);
                      }}
                      aria-label={`Delete ${connection.name}`}
                    >
                      Delete
                    </Button>
                  </div>
                </Td>
              </tr>
            );
          })}
        </Table>
      )}

      {editing && catalog.data && (
        <ConnectionForm
          catalog={catalog.data}
          connection={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void list.reload();
          }}
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
          Its stored credentials are removed. A connection that an action still uses cannot be deleted.
        </ConfirmDialog>
      )}
    </>
  );
}
