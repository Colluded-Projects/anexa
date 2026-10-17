import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ConnectorSpec, FieldSpec, Workspace } from "../api/types";
import { WorkspaceProvider } from "../auth/AuthContext";

export const WS: Workspace = {
  id: "ws1",
  name: "Acme",
  slug: "acme",
  role: "owner",
  created_at: "2026-10-01T00:00:00.000Z",
};

export const BASE = "/api/workspaces/ws1";

/** Render a page as it appears inside the shell, with a workspace and a router. */
export function renderInWorkspace(
  ui: ReactElement,
  { route = "/", path = "*", workspace = WS }: { route?: string; path?: string; workspace?: Workspace } = {},
) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <WorkspaceProvider workspace={workspace}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="/runs/:runId" element={<p>run page</p>} />
        </Routes>
      </WorkspaceProvider>
    </MemoryRouter>,
  );
}

export function field(overrides: Partial<FieldSpec> & { name: string }): FieldSpec {
  return {
    label: overrides.name,
    type: "string",
    required: false,
    secret: false,
    help: "",
    default: null,
    options: [],
    placeholder: "",
    ...overrides,
  };
}

export const CATALOG: ConnectorSpec[] = [
  {
    key: "slack",
    title: "Slack",
    description: "Messages and channels",
    config_fields: [
      field({ name: "bot_token", label: "Bot token", required: true, secret: true }),
      field({ name: "default_channel", label: "Default channel" }),
    ],
    operations: [
      {
        name: "post_message",
        title: "Post message",
        description: "Send a message to a channel.",
        kind: "action",
        params: [
          field({ name: "channel", label: "Channel", required: true }),
          field({ name: "text", label: "Text", type: "text", required: true }),
        ],
      },
      {
        name: "sync_users",
        title: "Sync users",
        description: "Import workspace members.",
        kind: "sync",
        params: [field({ name: "limit", label: "Limit", type: "number", default: 200 })],
      },
    ],
  },
  {
    key: "jira",
    title: "Jira",
    description: "Issues and projects",
    config_fields: [
      field({ name: "base_url", label: "Site URL", required: true }),
      field({ name: "email", label: "Email", required: true }),
      field({ name: "api_token", label: "API token", required: true, secret: true }),
    ],
    operations: [
      {
        name: "search_issues",
        title: "Search issues",
        description: "Run a JQL search.",
        kind: "action",
        params: [field({ name: "jql", label: "JQL", required: true })],
      },
    ],
  },
];
