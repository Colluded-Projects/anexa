import { useState, type FormEvent } from "react";
import { errorMessage, type ApiKey, type Member, type Role } from "../api";
import { useCurrentUser, useWorkspace } from "../auth/AuthContext";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CodeBlock,
  ConfirmDialog,
  ErrorNote,
  Input,
  Loading,
  Note,
  PageHeader,
  Select,
} from "../components/ui";
import { formatDateTime, formatRelative } from "../lib/format";
import { useAsync } from "../lib/hooks";

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
    setTimeout(() => setState("idle"), 2000);
  }

  return (
    <Button size="sm" onClick={() => void copy()}>
      <span aria-live="polite">
        {state === "copied" ? "Copied" : state === "failed" ? "Select and copy manually" : label}
      </span>
    </Button>
  );
}

function Members() {
  const { api, workspace } = useWorkspace();
  const user = useCurrentUser();
  const isOwner = workspace.role === "owner";
  const members = useAsync(() => api.members.list(), [api]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  async function invite(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.members.add(email.trim(), role);
      setEmail("");
      await members.reload();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      await api.members.remove(removing.user_id);
      setRemoving(null);
      await members.reload();
    } catch (cause) {
      setRemoveError(errorMessage(cause));
    } finally {
      setRemoveBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Members" />
      <div className="space-y-4 p-4">
        <ErrorNote message={members.error} onRetry={() => void members.reload()} />
        {members.loading ? (
          <Loading label="Loading members" />
        ) : (
          <ul className="divide-y divide-line">
            {(members.data ?? []).map((member) => (
              <li key={member.user_id} className="flex flex-wrap items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">
                    {member.name || member.email}
                    {member.user_id === user?.id && <span className="font-normal text-muted"> (you)</span>}
                  </p>
                  <p className="truncate text-xs text-muted">{member.email}</p>
                </div>
                <Badge tone={member.role === "owner" ? "accent" : "neutral"}>{member.role}</Badge>
                {isOwner && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setRemoveError(null);
                      setRemoving(member);
                    }}
                    aria-label={`Remove ${member.email}`}
                  >
                    Remove
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}

        {isOwner ? (
          <form onSubmit={invite} className="space-y-2 border-t border-line pt-4">
            <label htmlFor="member-email" className="block text-sm font-medium">
              Add a member by email
            </label>
            <div className="flex flex-wrap gap-2">
              <div className="min-w-52 flex-1">
                <Input
                  id="member-email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="teammate@company.com"
                  aria-describedby="member-email-help"
                  required
                />
              </div>
              <label htmlFor="member-role" className="sr-only">
                Role
              </label>
              <Select
                id="member-role"
                className="w-32!"
                value={role}
                onChange={(event) => setRole(event.target.value as Role)}
              >
                <option value="member">Member</option>
                <option value="owner">Owner</option>
              </Select>
              <Button type="submit" variant="primary" busy={busy} disabled={!email.trim()}>
                Add
              </Button>
            </div>
            <p id="member-email-help" className="text-xs text-muted">
              They need to have signed up already; no invitation email is sent.
            </p>
            <ErrorNote message={error} />
          </form>
        ) : (
          <Note>Only workspace owners can add or remove members.</Note>
        )}
      </div>

      {removing && (
        <ConfirmDialog
          title={`Remove ${removing.email}?`}
          confirmLabel="Remove"
          busy={removeBusy}
          error={removeError}
          onCancel={() => setRemoving(null)}
          onConfirm={() => void confirmRemove()}
        >
          They lose access to this workspace. The last owner cannot be removed.
        </ConfirmDialog>
      )}
    </Card>
  );
}

function ApiKeys({
  onCreated,
  version,
}: {
  onCreated: (key: string) => void;
  /** Bumped when a key is created elsewhere on the page, to reload the list. */
  version: number;
}) {
  const { api } = useWorkspace();
  const keys = useAsync(() => api.apiKeys.list(), [api, version]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<ApiKey | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const key = await api.apiKeys.create(name.trim());
      setCreated(key);
      if (key.key) onCreated(key.key);
      setName("");
      await keys.reload();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function confirmRevoke() {
    if (!revoking) return;
    setRevokeBusy(true);
    setRevokeError(null);
    try {
      await api.apiKeys.remove(revoking.id);
      if (created?.id === revoking.id) setCreated(null);
      setRevoking(null);
      await keys.reload();
    } catch (cause) {
      setRevokeError(errorMessage(cause));
    } finally {
      setRevokeBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="API keys" />
      <div className="space-y-4 p-4">
        <p className="text-sm text-muted">
          A key acts as you inside this workspace. The MCP server uses one to create and run actions
          and operators from Claude Code.
        </p>

        {created?.key && (
          <div role="status" className="space-y-2 rounded-md border border-ok/40 bg-ok-soft p-3">
            <p className="text-sm font-medium text-ink">
              Copy the key for “{created.name}” now. It will not be shown again.
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1.5 font-mono text-xs break-all">
                {created.key}
              </code>
              <CopyButton text={created.key} label="Copy key" />
            </div>
          </div>
        )}

        <ErrorNote message={keys.error} onRetry={() => void keys.reload()} />
        {keys.loading ? (
          <Loading label="Loading keys" />
        ) : (keys.data ?? []).length === 0 ? (
          <p className="text-sm text-muted">No keys yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {(keys.data ?? []).map((key) => (
              <li key={key.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{key.name}</p>
                  <p className="text-xs text-muted">
                    <code className="font-mono">{key.prefix}…</code> · created {formatDateTime(key.created_at)} ·{" "}
                    {key.last_used_at ? `last used ${formatRelative(key.last_used_at)}` : "never used"}
                  </p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setRevokeError(null);
                    setRevoking(key);
                  }}
                  aria-label={`Revoke ${key.name}`}
                >
                  Revoke
                </Button>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={create} className="space-y-2 border-t border-line pt-4">
          <label htmlFor="api-key-name" className="block text-sm font-medium">
            New key name
          </label>
          <div className="flex flex-wrap gap-2">
            <div className="min-w-52 flex-1">
              <Input
                id="api-key-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Claude Code on my laptop"
                required
              />
            </div>
            <Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>
              Create key
            </Button>
          </div>
          <ErrorNote message={error} />
        </form>
      </div>

      {revoking && (
        <ConfirmDialog
          title={`Revoke ${revoking.name}?`}
          confirmLabel="Revoke"
          busy={revokeBusy}
          error={revokeError}
          onCancel={() => setRevoking(null)}
          onConfirm={() => void confirmRevoke()}
        >
          Anything using this key, including an MCP server configured with it, stops working immediately.
        </ConfirmDialog>
      )}
    </Card>
  );
}

/** `.mcp.json` for the HTTP endpoint: nothing to install, the key is the bearer token. */
export function mcpConfig(mcpUrl: string, apiKey: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        anexa: {
          type: "http",
          url: mcpUrl,
          headers: { Authorization: `Bearer ${apiKey}` },
        },
      },
    },
    null,
    2,
  );
}

/** `.mcp.json` for running the MCP server locally over stdio from a checkout. */
export function mcpStdioConfig(apiUrl: string, apiKey: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        anexa: {
          command: "uv",
          args: ["run", "--directory", "<repo>/backend", "anexa-mcp"],
          env: { ANEXA_API_URL: apiUrl, ANEXA_API_KEY: apiKey },
        },
      },
    },
    null,
    2,
  );
}

function defaultMcpUrl(): string {
  return `${window.location.origin}/mcp`;
}

const PLACEHOLDER_KEY = "<your API key>";

function ConnectClaudeCode({
  apiKey,
  onGenerated,
}: {
  apiKey: string | null;
  onGenerated: (key: string) => void;
}) {
  const { api } = useWorkspace();
  const [mcpUrl, setMcpUrl] = useState(defaultMcpUrl);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = apiKey ?? PLACEHOLDER_KEY;
  const config = mcpConfig(mcpUrl, key);
  const command = `claude mcp add --transport http anexa ${mcpUrl} --header "Authorization: Bearer ${key}"`;
  const apiUrl = mcpUrl.replace(/\/mcp\/?$/, "");

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const created = await api.apiKeys.create("Claude Code (MCP)");
      if (created.key) onGenerated(created.key);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Connect Claude Code" />
      <div className="space-y-4 p-4">
        <p className="text-sm text-muted">
          The MCP server lets Claude Code create connections, actions and operators, start runs and
          read the company graph. Generate a config, then paste it into{" "}
          <code className="font-mono">.mcp.json</code> in your project or straight into a Claude Code
          conversation.
        </p>

        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-0 max-w-md flex-1 space-y-1.5">
            <label htmlFor="mcp-url" className="block text-sm font-medium">
              MCP server URL as seen from your machine
            </label>
            <Input id="mcp-url" value={mcpUrl} onChange={(event) => setMcpUrl(event.target.value)} />
          </div>
          <Button onClick={() => void generate()} disabled={busy}>
            {busy ? "Generating…" : apiKey ? "Generate a new token" : "Generate MCP config"}
          </Button>
        </div>
        <ErrorNote message={error} />
        {apiKey ? (
          <Note>
            This config contains a new API key as its bearer token. Copy it now: the key is not shown
            again. It acts as you in this workspace and can be revoked under API keys.
          </Note>
        ) : (
          <p className="text-sm text-muted">
            Generating creates an API key named “Claude Code (MCP)” and fills it in as the bearer token.
          </p>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium">
              Project config (<code className="font-mono">.mcp.json</code>)
            </h3>
            <CopyButton text={config} label="Copy config" />
          </div>
          <CodeBlock label="MCP configuration">{config}</CodeBlock>
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium">Or from a terminal</h3>
            <CopyButton text={command} label="Copy command" />
          </div>
          <CodeBlock label="Claude Code command">{command}</CodeBlock>
        </div>
        <details className="text-sm">
          <summary className="cursor-pointer text-muted">
            Run the MCP server locally over stdio instead
          </summary>
          <div className="mt-2 space-y-2">
            <p className="text-muted">
              Needs a checkout of this project and uv. Replace{" "}
              <code className="font-mono">&lt;repo&gt;</code> with its path.
            </p>
            <CodeBlock label="Local stdio configuration">{mcpStdioConfig(apiUrl, key)}</CodeBlock>
          </div>
        </details>
      </div>
    </Card>
  );
}

export function SettingsPage() {
  const { workspace } = useWorkspace();
  const [newKey, setNewKey] = useState<string | null>(null);
  const [keysVersion, setKeysVersion] = useState(0);

  return (
    <>
      <PageHeader
        title="Settings"
        description={`${workspace.name} · you are ${workspace.role === "owner" ? "an owner" : "a member"}`}
      />
      <div className="space-y-6">
        <Members />
        <ApiKeys onCreated={setNewKey} version={keysVersion} />
        <ConnectClaudeCode
          apiKey={newKey}
          onGenerated={(key) => {
            setNewKey(key);
            setKeysVersion((version) => version + 1);
          }}
        />
      </div>
    </>
  );
}
