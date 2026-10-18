import { useEffect, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { errorMessage } from "../api";
import { useAuth, WorkspaceProvider } from "../auth/AuthContext";
import { Button, cx, ErrorNote, Field, FormActions, Input, Modal, Select } from "./ui";

const NAV: { to: string; label: string; end?: boolean }[][] = [
  [{ to: "/", label: "Overview", end: true }],
  [
    { to: "/connections", label: "Connections" },
    { to: "/actions", label: "Actions" },
    { to: "/operators", label: "Operators" },
    { to: "/schedules", label: "Schedules" },
    { to: "/runs", label: "Runs" },
  ],
  [
    { to: "/graph", label: "Company graph" },
    { to: "/agents", label: "Agents" },
  ],
  [{ to: "/settings", label: "Settings" }],
];

function Logo() {
  return (
    <div className="flex items-center gap-2 text-ink">
      <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden="true">
        <path d="M9 9L23 12L14 24Z" fill="none" stroke="var(--color-accent)" strokeWidth="2" />
        <circle cx="9" cy="9" r="5" fill="var(--color-accent)" />
        <circle cx="23" cy="12" r="4" fill="var(--color-accent)" />
        <circle cx="14" cy="24" r="4" fill="var(--color-accent)" />
      </svg>
      <span className="text-[15px] font-semibold tracking-tight">Anexa</span>
    </div>
  );
}

function CreateWorkspaceDialog({ onClose }: { onClose: () => void }) {
  const { createWorkspace } = useAuth();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createWorkspace(name.trim());
      onClose();
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title="New workspace" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Workspace name"
          htmlFor="new-workspace-name"
          help="Connections, operators and the company graph are kept separate per workspace."
        >
          <Input
            id="new-workspace-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            aria-describedby="new-workspace-name-help"
          />
        </Field>
        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>
            Create workspace
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}

export function Shell() {
  const { user, workspaces, workspace, selectWorkspace, logout } = useAuth();
  const [creating, setCreating] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setMenuOpen(false), [location.pathname]);

  return (
    <div className="min-h-screen md:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <div className="flex items-center justify-between border-b border-line bg-surface px-4 py-3 md:hidden">
        <Logo />
        <Button
          size="sm"
          aria-expanded={menuOpen}
          aria-controls="sidebar"
          onClick={() => setMenuOpen((open) => !open)}
        >
          Menu
        </Button>
      </div>

      <aside
        id="sidebar"
        className={cx(
          "shrink-0 border-line bg-surface md:sticky md:top-0 md:flex md:h-screen md:w-60 md:flex-col md:border-r",
          menuOpen ? "block border-b" : "hidden",
        )}
      >
        <div className="hidden px-5 pt-5 pb-4 md:block">
          <Logo />
        </div>

        <div className="px-3 pt-3 md:pt-0">
          <label htmlFor="workspace-switcher" className="sr-only">
            Workspace
          </label>
          <Select
            id="workspace-switcher"
            value={workspace?.id ?? ""}
            onChange={(event) => {
              if (event.target.value === "__new__") setCreating(true);
              else selectWorkspace(event.target.value);
            }}
          >
            {workspaces.map((ws) => (
              <option key={ws.id} value={ws.id}>
                {ws.name}
              </option>
            ))}
            <option value="__new__">+ New workspace…</option>
          </Select>
        </div>

        <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
          {NAV.map((group, index) => (
            <ul key={index} className={cx("space-y-0.5", index > 0 && "mt-4 border-t border-line pt-4")}>
              {group.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      cx(
                        "block rounded-md px-3 py-2 text-sm",
                        isActive
                          ? "bg-accent-soft font-medium text-accent"
                          : "text-muted hover:bg-sunken hover:text-ink",
                      )
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          ))}
        </nav>

        <div className="border-t border-line px-4 py-3">
          <p className="truncate text-sm font-medium text-ink">{user?.name || user?.email}</p>
          <p className="truncate text-xs text-muted">{user?.email}</p>
          <button
            type="button"
            onClick={logout}
            className="mt-2 text-xs font-medium text-muted underline hover:text-ink"
          >
            Sign out
          </button>
        </div>
      </aside>

      <main id="main" className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">
        <div className="mx-auto max-w-6xl">
          {workspace ? (
            // Remount pages when the workspace changes so no stale data survives the switch.
            <WorkspaceProvider key={workspace.id} workspace={workspace}>
              <Outlet />
            </WorkspaceProvider>
          ) : (
            <div className="rounded-lg border border-dashed border-line-strong px-6 py-12 text-center">
              <h1 className="text-base font-semibold">You are not in a workspace yet</h1>
              <p className="mt-1.5 text-sm text-muted">
                Create one, or ask a workspace owner to add you by email.
              </p>
              <div className="mt-5">
                <Button variant="primary" onClick={() => setCreating(true)}>
                  Create workspace
                </Button>
              </div>
            </div>
          )}
        </div>
      </main>

      {creating && <CreateWorkspaceDialog onClose={() => setCreating(false)} />}
    </div>
  );
}
