import { useMemo, useState, type FormEvent } from "react";
import {
  connectors as connectorsApi,
  errorMessage,
  type Action,
  type Connection,
  type ConnectorSpec,
  type JsonObject,
} from "../api";
import { useWorkspace } from "../auth/AuthContext";
import { FieldsForm } from "../components/FieldsForm";
import { JsonField, TemplateHint } from "../components/JsonField";
import { RunDialog } from "../components/RunDialog";
import {
  Badge,
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
  Table,
  Td,
} from "../components/ui";
import {
  collectValues,
  extraValues,
  initialValues,
  missingRequired,
  type FieldValues,
} from "../lib/fields";
import { formatRelative } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { parseJsonObject, prettyJson } from "../lib/json";

interface FormProps {
  catalog: ConnectorSpec[];
  connections: Connection[];
  action?: Action;
  onSaved: (action: Action) => void;
  onClose: () => void;
}

export function ActionForm({ catalog, connections, action, onSaved, onClose }: FormProps) {
  const { api } = useWorkspace();
  const [name, setName] = useState(action?.name ?? "");
  const [description, setDescription] = useState(action?.description ?? "");
  const [connectionId, setConnectionId] = useState(action?.connection_id ?? connections[0]?.id ?? "");
  const connection = connections.find((item) => item.id === connectionId);
  const spec = catalog.find((item) => item.key === connection?.connector);
  const [operationName, setOperationName] = useState(
    action?.operation ?? spec?.operations[0]?.name ?? "",
  );
  const operation = spec?.operations.find((item) => item.name === operationName);
  const fields = useMemo(() => operation?.params ?? [], [operation]);

  const stored: JsonObject = action?.params ?? {};
  const [values, setValues] = useState<FieldValues>(() => initialValues(fields, stored));
  // Params the operation does not describe are kept as-is while editing in the form.
  const [extras, setExtras] = useState<JsonObject>(() => extraValues(fields, stored));
  const [mode, setMode] = useState<"form" | "json">("form");
  const [jsonText, setJsonText] = useState(() => prettyJson(stored));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function currentParams(): JsonObject {
    return { ...extras, ...collectValues(fields, values) };
  }

  function resetParams(nextConnectionId: string, nextOperation: string) {
    const nextSpec = catalog.find(
      (item) => item.key === connections.find((c) => c.id === nextConnectionId)?.connector,
    );
    const nextFields = nextSpec?.operations.find((op) => op.name === nextOperation)?.params ?? [];
    setValues(initialValues(nextFields));
    setExtras({});
    setJsonText("{}");
  }

  function chooseConnection(id: string) {
    const nextSpec = catalog.find(
      (item) => item.key === connections.find((c) => c.id === id)?.connector,
    );
    const nextOperation = nextSpec?.operations[0]?.name ?? "";
    setConnectionId(id);
    setOperationName(nextOperation);
    resetParams(id, nextOperation);
  }

  function chooseOperation(next: string) {
    setOperationName(next);
    resetParams(connectionId, next);
  }

  function switchMode(next: "form" | "json") {
    if (next === mode) return;
    if (next === "json") {
      setJsonText(prettyJson(currentParams()));
    } else {
      const parsed = parseJsonObject(jsonText);
      if (!parsed.ok) {
        setError(`Fix the JSON before switching back to the form: ${parsed.error}`);
        return;
      }
      setValues(initialValues(fields, parsed.value));
      setExtras(extraValues(fields, parsed.value));
    }
    setError(null);
    setMode(next);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    let params: JsonObject;
    if (mode === "json") {
      const parsed = parseJsonObject(jsonText);
      if (!parsed.ok) {
        setError(`Params are not valid JSON: ${parsed.error}`);
        return;
      }
      params = parsed.value;
    } else {
      const missing = missingRequired(fields, values);
      if (missing.length) {
        setError(`Fill in: ${missing.join(", ")}.`);
        return;
      }
      params = currentParams();
    }
    setBusy(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        description: description.trim(),
        connection_id: connectionId,
        operation: operationName,
        params,
      };
      onSaved(action ? await api.actions.update(action.id, body) : await api.actions.create(body));
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={action ? `Edit ${action.name}` : "New action"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="action-name" required>
            <Input
              id="action-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Post to #eng"
              required
            />
          </Field>
          <Field label="Description" htmlFor="action-description">
            <Input
              id="action-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
          <Field label="Connection" htmlFor="action-connection" required>
            <Select
              id="action-connection"
              value={connectionId}
              onChange={(event) => chooseConnection(event.target.value)}
            >
              {connections.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.connector})
                </option>
              ))}
            </Select>
          </Field>
          <Field
            label="Operation"
            htmlFor="action-operation"
            required
            help={
              operation
                ? `${operation.description}${operation.kind === "sync" ? " Writes into the company graph." : ""}`
                : undefined
            }
          >
            <Select
              id="action-operation"
              value={operationName}
              aria-describedby="action-operation-help"
              onChange={(event) => chooseOperation(event.target.value)}
            >
              {!operation && <option value={operationName}>{operationName || "Choose…"}</option>}
              {spec?.operations.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.title}
                  {item.kind === "sync" ? " (sync)" : ""}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <fieldset className="space-y-4 rounded-md border border-line p-4">
          <legend className="px-1 text-sm font-medium">Params</legend>
          <div className="flex gap-1.5" role="group" aria-label="Params editor">
            <Button
              size="sm"
              variant={mode === "form" ? "secondary" : "ghost"}
              aria-pressed={mode === "form"}
              onClick={() => switchMode("form")}
            >
              Form
            </Button>
            <Button
              size="sm"
              variant={mode === "json" ? "secondary" : "ghost"}
              aria-pressed={mode === "json"}
              onClick={() => switchMode("json")}
            >
              Raw JSON
            </Button>
          </div>

          {mode === "form" ? (
            <>
              <FieldsForm
                key={`${connectionId}:${operationName}`}
                idPrefix="action-param"
                fields={fields}
                values={values}
                allowTemplates
                onChange={(field, value) => setValues((current) => ({ ...current, [field]: value }))}
              />
              {Object.keys(extras).length > 0 && (
                <Note>
                  {Object.keys(extras).length} extra param(s) not described by this operation are kept:{" "}
                  <code className="font-mono">{Object.keys(extras).join(", ")}</code>. Edit them in raw
                  JSON.
                </Note>
              )}
            </>
          ) : (
            <JsonField
              id="action-params-json"
              label="Params as JSON"
              value={jsonText}
              onChange={setJsonText}
              rows={9}
            />
          )}
          <TemplateHint />
        </fieldset>

        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            type="submit"
            variant="primary"
            busy={busy}
            disabled={!name.trim() || !connectionId || !operationName}
          >
            {action ? "Save changes" : "Create action"}
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}

export function ActionsPage() {
  const { api } = useWorkspace();
  const data = useAsync(
    async () => {
      const [actions, connections, catalog] = await Promise.all([
        api.actions.list(),
        api.connections.list(),
        connectorsApi.list(),
      ]);
      return { actions, connections, catalog };
    },
    [api],
  );

  const [editing, setEditing] = useState<Action | "new" | null>(null);
  const [running, setRunning] = useState<Action | null>(null);
  const [deleting, setDeleting] = useState<Action | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function confirmDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.actions.remove(deleting.id);
      setDeleting(null);
      await data.reload();
    } catch (cause) {
      setDeleteError(errorMessage(cause));
    } finally {
      setDeleteBusy(false);
    }
  }

  const actions = data.data?.actions ?? [];
  const hasConnections = (data.data?.connections.length ?? 0) > 0;
  const newButton = (
    <Button variant="primary" disabled={!hasConnections} onClick={() => setEditing("new")}>
      New action
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Actions"
        description="One reusable call to a connected system, such as posting a message or searching issues. Operators chain actions together."
        actions={newButton}
      />
      <ErrorNote message={data.error} className="mb-4" onRetry={() => void data.reload()} />

      {data.loading ? (
        <Loading label="Loading actions" />
      ) : data.data && !hasConnections ? (
        <EmptyState title="Add a connection first">
          An action runs against a connection. Create one under Connections, then come back.
        </EmptyState>
      ) : actions.length === 0 && !data.error ? (
        <EmptyState title="No actions yet" action={newButton}>
          Pick a connection and one of its operations, fill in the params, and run it or use it in an
          operator.
        </EmptyState>
      ) : (
        <Table head={["Name", "Connection", "Operation", "Updated", <span className="sr-only">Actions</span>]}>
          {actions.map((action) => (
            <tr key={action.id}>
              <Td>
                <div className="font-medium text-ink">{action.name}</div>
                {action.description && <div className="text-xs text-muted">{action.description}</div>}
              </Td>
              <Td className="text-muted">{action.connection_name}</Td>
              <Td>
                <Badge>
                  {action.connector}.{action.operation}
                </Badge>
              </Td>
              <Td className="text-muted">{formatRelative(action.updated_at)}</Td>
              <Td>
                <div className="flex justify-end gap-1.5">
                  <Button size="sm" onClick={() => setRunning(action)} aria-label={`Run ${action.name}`}>
                    Run
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setEditing(action)}
                    aria-label={`Edit ${action.name}`}
                  >
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setDeleteError(null);
                      setDeleting(action);
                    }}
                    aria-label={`Delete ${action.name}`}
                  >
                    Delete
                  </Button>
                </div>
              </Td>
            </tr>
          ))}
        </Table>
      )}

      {editing && data.data && (
        <ActionForm
          catalog={data.data.catalog}
          connections={data.data.connections}
          action={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void data.reload();
          }}
        />
      )}
      {running && (
        <RunDialog
          title={`Run ${running.name}`}
          start={(input) => api.actions.run(running.id, input)}
          onClose={() => setRunning(null)}
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
          An action that an operator still uses cannot be deleted.
        </ConfirmDialog>
      )}
    </>
  );
}
