import { useState, type FormEvent } from "react";
import {
  errorMessage,
  type Action,
  type Agent,
  type AgentProvider,
  type Operator,
} from "../api";
import { useWorkspace } from "../auth/AuthContext";
import {
  Badge,
  Button,
  Card,
  Checkbox,
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
  Textarea,
} from "../components/ui";
import { useAsync } from "../lib/hooks";

const PROVIDERS: { value: AgentProvider; label: string; hint: string }[] = [
  { value: "claude_code", label: "Claude Code", hint: "e.g. claude-opus-5-5" },
  { value: "openrouter", label: "OpenRouter", hint: "e.g. anthropic/claude-sonnet-5" },
  { value: "jev", label: "Jev (TypeSafe AI)", hint: "decision model id" },
  { value: "custom", label: "Custom", hint: "model or endpoint name" },
];

const providerLabel = (value: string) =>
  PROVIDERS.find((provider) => provider.value === value)?.label ?? value;

function toggleId(ids: string[], id: string, on: boolean): string[] {
  return on ? [...new Set([...ids, id])] : ids.filter((item) => item !== id);
}

interface FormProps {
  agent?: Agent;
  actions: Action[];
  operators: Operator[];
  onSaved: (agent: Agent) => void;
  onClose: () => void;
}

export function AgentForm({ agent, actions, operators, onSaved, onClose }: FormProps) {
  const { api } = useWorkspace();
  const [name, setName] = useState(agent?.name ?? "");
  const [description, setDescription] = useState(agent?.description ?? "");
  const [provider, setProvider] = useState<AgentProvider>(agent?.provider ?? "claude_code");
  const [model, setModel] = useState(agent?.model ?? "");
  const [instructions, setInstructions] = useState(agent?.instructions ?? "");
  const [actionIds, setActionIds] = useState<string[]>(agent?.action_ids ?? []);
  const [operatorIds, setOperatorIds] = useState<string[]>(agent?.operator_ids ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = {
        name: name.trim(),
        description: description.trim(),
        provider,
        model: model.trim(),
        instructions,
        action_ids: actionIds,
        operator_ids: operatorIds,
      };
      onSaved(agent ? await api.agents.update(agent.id, body) : await api.agents.create(body));
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={agent ? `Edit ${agent.name}` : "New agent"} onClose={onClose} wide>
      <form onSubmit={submit} className="space-y-4">
        <Note>
          This saves the agent's definition only. No agent runtime is attached yet, so it will not act
          on anything.
        </Note>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="agent-name" required>
            <Input id="agent-name" value={name} onChange={(event) => setName(event.target.value)} required />
          </Field>
          <Field label="Description" htmlFor="agent-description">
            <Input
              id="agent-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </Field>
          <Field label="Provider" htmlFor="agent-provider">
            <Select
              id="agent-provider"
              value={provider}
              onChange={(event) => setProvider(event.target.value as AgentProvider)}
            >
              {PROVIDERS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Model" htmlFor="agent-model">
            <Input
              id="agent-model"
              value={model}
              onChange={(event) => setModel(event.target.value)}
              placeholder={PROVIDERS.find((item) => item.value === provider)?.hint}
            />
          </Field>
        </div>
        <Field label="Instructions" htmlFor="agent-instructions">
          <Textarea
            id="agent-instructions"
            rows={4}
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            placeholder="What this agent is for and how it should behave."
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <fieldset className="rounded-md border border-line p-4">
            <legend className="px-1 text-sm font-medium">Linked actions</legend>
            {actions.length === 0 ? (
              <p className="text-sm text-muted">No actions exist yet.</p>
            ) : (
              <div className="max-h-48 space-y-2 overflow-y-auto">
                {actions.map((action) => (
                  <Checkbox
                    key={action.id}
                    label={action.name}
                    description={`${action.connector}.${action.operation}`}
                    checked={actionIds.includes(action.id)}
                    onChange={(event) => setActionIds(toggleId(actionIds, action.id, event.target.checked))}
                  />
                ))}
              </div>
            )}
          </fieldset>
          <fieldset className="rounded-md border border-line p-4">
            <legend className="px-1 text-sm font-medium">Linked operators</legend>
            {operators.length === 0 ? (
              <p className="text-sm text-muted">No operators exist yet.</p>
            ) : (
              <div className="max-h-48 space-y-2 overflow-y-auto">
                {operators.map((operator) => (
                  <Checkbox
                    key={operator.id}
                    label={operator.name}
                    description={`${operator.tasks.length} task(s)`}
                    checked={operatorIds.includes(operator.id)}
                    onChange={(event) =>
                      setOperatorIds(toggleId(operatorIds, operator.id, event.target.checked))
                    }
                  />
                ))}
              </div>
            )}
          </fieldset>
        </div>

        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>
            {agent ? "Save changes" : "Create agent"}
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}

export function AgentsPage() {
  const { api } = useWorkspace();
  const data = useAsync(
    async () => {
      const [agents, actions, operators] = await Promise.all([
        api.agents.list(),
        api.actions.list(),
        api.operators.list(),
      ]);
      return { agents, actions, operators };
    },
    [api],
  );
  const [editing, setEditing] = useState<Agent | "new" | null>(null);
  const [deleting, setDeleting] = useState<Agent | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function confirmDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.agents.remove(deleting.id);
      setDeleting(null);
      await data.reload();
    } catch (cause) {
      setDeleteError(errorMessage(cause));
    } finally {
      setDeleteBusy(false);
    }
  }

  const agents = data.data?.agents ?? [];
  const actionNames = new Map((data.data?.actions ?? []).map((item) => [item.id, item.name]));
  const operatorNames = new Map((data.data?.operators ?? []).map((item) => [item.id, item.name]));
  const newButton = (
    <Button variant="primary" onClick={() => setEditing("new")}>
      New agent
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Agents"
        description="Define agents and the actions and operators they will be allowed to use."
        actions={newButton}
      />
      <Note className="mb-5">
        <strong className="font-semibold text-ink">Agents are placeholders for now.</strong> You can
        describe an agent and link actions and operators to it, but no model or runtime is connected, so
        every agent shows as not connected and does nothing on its own.
      </Note>
      <ErrorNote message={data.error} className="mb-4" onRetry={() => void data.reload()} />

      {data.loading ? (
        <Loading label="Loading agents" />
      ) : agents.length === 0 && !data.error ? (
        <EmptyState title="No agents defined" action={newButton}>
          Sketch out an agent now so its actions and operators are ready when a runtime is attached.
        </EmptyState>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {agents.map((agent) => (
            <li key={agent.id}>
              <Card className="flex h-full flex-col p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-[15px] font-semibold">{agent.name}</h2>
                    <p className="text-xs text-muted">
                      {providerLabel(agent.provider)}
                      {agent.model && ` · ${agent.model}`}
                    </p>
                  </div>
                  <Badge tone="warn">Not connected</Badge>
                </div>
                {agent.description && <p className="mt-2 text-sm text-muted">{agent.description}</p>}

                <dl className="mt-3 space-y-2 text-xs">
                  <div>
                    <dt className="font-medium text-ink">Actions</dt>
                    <dd className="text-muted">
                      {agent.action_ids.length
                        ? agent.action_ids.map((id) => actionNames.get(id) ?? "deleted action").join(", ")
                        : "None linked"}
                    </dd>
                  </div>
                  <div>
                    <dt className="font-medium text-ink">Operators</dt>
                    <dd className="text-muted">
                      {agent.operator_ids.length
                        ? agent.operator_ids.map((id) => operatorNames.get(id) ?? "deleted operator").join(", ")
                        : "None linked"}
                    </dd>
                  </div>
                </dl>

                <div className="mt-auto flex justify-end gap-1.5 pt-4">
                  <Button size="sm" variant="ghost" onClick={() => setEditing(agent)} aria-label={`Edit ${agent.name}`}>
                    Edit
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setDeleteError(null);
                      setDeleting(agent);
                    }}
                    aria-label={`Delete ${agent.name}`}
                  >
                    Delete
                  </Button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {editing && data.data && (
        <AgentForm
          agent={editing === "new" ? undefined : editing}
          actions={data.data.actions}
          operators={data.data.operators}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void data.reload();
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
          Only the agent definition is removed. Its linked actions and operators are untouched.
        </ConfirmDialog>
      )}
    </>
  );
}
