import { request } from "./client";
import type {
  Action,
  ActionInput,
  Agent,
  AgentInput,
  ApiKey,
  AuthResult,
  Connection,
  ConnectionInput,
  ConnectionTest,
  ConnectorSpec,
  GraphEdge,
  GraphNode,
  GraphNodeDetail,
  GraphStats,
  JsonObject,
  LinkResult,
  LinkReviewRow,
  LinkScore,
  Me,
  Member,
  Ontology,
  Operator,
  OperatorInput,
  Role,
  Run,
  RunKind,
  RunStatus,
  Schedule,
  ScheduleInput,
  Subgraph,
  Summary,
  Workspace,
} from "./types";

export * from "./client";
export type * from "./types";

export const auth = {
  signup: (body: { email: string; password: string; name: string; workspace_name?: string }) =>
    request<AuthResult>("/api/auth/signup", { method: "POST", body }),
  login: (body: { email: string; password: string }) =>
    request<AuthResult>("/api/auth/login", { method: "POST", body }),
  me: () => request<Me>("/api/me"),
};

export const workspaces = {
  list: () => request<Workspace[]>("/api/workspaces"),
  create: (name: string) =>
    request<Workspace>("/api/workspaces", { method: "POST", body: { name } }),
};

export const connectors = {
  list: () => request<ConnectorSpec[]>("/api/connectors"),
};

/** Everything scoped to one workspace. */
export function workspaceApi(workspaceId: string) {
  const base = `/api/workspaces/${encodeURIComponent(workspaceId)}`;
  const id = (value: string) => encodeURIComponent(value);

  return {
    summary: () => request<Summary>(`${base}/summary`),

    members: {
      list: () => request<Member[]>(`${base}/members`),
      add: (email: string, role: Role = "member") =>
        request<Member>(`${base}/members`, { method: "POST", body: { email, role } }),
      remove: (userId: string) =>
        request<void>(`${base}/members/${id(userId)}`, { method: "DELETE" }),
    },

    apiKeys: {
      list: () => request<ApiKey[]>(`${base}/api-keys`),
      create: (name: string) =>
        request<ApiKey>(`${base}/api-keys`, { method: "POST", body: { name } }),
      remove: (keyId: string) =>
        request<void>(`${base}/api-keys/${id(keyId)}`, { method: "DELETE" }),
    },

    connections: {
      list: () => request<Connection[]>(`${base}/connections`),
      create: (body: ConnectionInput) =>
        request<Connection>(`${base}/connections`, { method: "POST", body }),
      update: (connectionId: string, body: ConnectionInput) =>
        request<Connection>(`${base}/connections/${id(connectionId)}`, { method: "PATCH", body }),
      remove: (connectionId: string) =>
        request<void>(`${base}/connections/${id(connectionId)}`, { method: "DELETE" }),
      test: (connectionId: string) =>
        request<ConnectionTest>(`${base}/connections/${id(connectionId)}/test`, { method: "POST" }),
    },

    actions: {
      list: () => request<Action[]>(`${base}/actions`),
      create: (body: ActionInput) => request<Action>(`${base}/actions`, { method: "POST", body }),
      update: (actionId: string, body: Partial<ActionInput>) =>
        request<Action>(`${base}/actions/${id(actionId)}`, { method: "PATCH", body }),
      remove: (actionId: string) =>
        request<void>(`${base}/actions/${id(actionId)}`, { method: "DELETE" }),
      run: (actionId: string, input: JsonObject = {}) =>
        request<Run>(`${base}/actions/${id(actionId)}/run`, { method: "POST", body: { input } }),
    },

    operators: {
      list: () => request<Operator[]>(`${base}/operators`),
      create: (body: OperatorInput) =>
        request<Operator>(`${base}/operators`, { method: "POST", body }),
      update: (operatorId: string, body: Partial<OperatorInput>) =>
        request<Operator>(`${base}/operators/${id(operatorId)}`, { method: "PATCH", body }),
      remove: (operatorId: string) =>
        request<void>(`${base}/operators/${id(operatorId)}`, { method: "DELETE" }),
      run: (operatorId: string, input: JsonObject = {}) =>
        request<Run>(`${base}/operators/${id(operatorId)}/run`, {
          method: "POST",
          body: { input },
        }),
    },

    schedules: {
      list: (operatorId?: string) =>
        request<Schedule[]>(`${base}/schedules`, { query: { operator_id: operatorId } }),
      create: (body: ScheduleInput) =>
        request<Schedule>(`${base}/schedules`, { method: "POST", body }),
      update: (scheduleId: string, body: Partial<Omit<ScheduleInput, "operator_id">>) =>
        request<Schedule>(`${base}/schedules/${id(scheduleId)}`, { method: "PATCH", body }),
      remove: (scheduleId: string) =>
        request<void>(`${base}/schedules/${id(scheduleId)}`, { method: "DELETE" }),
    },

    runs: {
      list: (filter: { kind?: RunKind; status?: RunStatus; target_id?: string; limit?: number } = {}) =>
        request<Run[]>(`${base}/runs`, { query: filter }),
      get: (runId: string) => request<Run>(`${base}/runs/${id(runId)}`),
    },

    agents: {
      list: () => request<Agent[]>(`${base}/agents`),
      create: (body: AgentInput) => request<Agent>(`${base}/agents`, { method: "POST", body }),
      update: (agentId: string, body: Partial<AgentInput>) =>
        request<Agent>(`${base}/agents/${id(agentId)}`, { method: "PATCH", body }),
      remove: (agentId: string) =>
        request<void>(`${base}/agents/${id(agentId)}`, { method: "DELETE" }),
    },

    graph: {
      ontology: () => request<Ontology>(`${base}/graph/ontology`),
      stats: () => request<GraphStats>(`${base}/graph/stats`),
      nodes: (filter: { label?: string; q?: string; limit?: number } = {}) =>
        request<GraphNode[]>(`${base}/graph/nodes`, { query: filter }),
      node: (nodeId: string) => request<GraphNodeDetail>(`${base}/graph/nodes/${id(nodeId)}`),
      createNode: (body: { label: string; name: string; key?: string; props?: JsonObject }) =>
        request<GraphNode>(`${base}/graph/nodes`, { method: "POST", body }),
      updateNode: (nodeId: string, body: { name?: string; props?: JsonObject }) =>
        request<GraphNode>(`${base}/graph/nodes/${id(nodeId)}`, { method: "PATCH", body }),
      removeNode: (nodeId: string) =>
        request<void>(`${base}/graph/nodes/${id(nodeId)}`, { method: "DELETE" }),
      createEdge: (body: { src: string; type: string; dst: string; props?: JsonObject }) =>
        request<GraphEdge>(`${base}/graph/edges`, { method: "POST", body }),
      removeEdge: (edge: { src: string; type: string; dst: string }) =>
        request<void>(`${base}/graph/edges`, { method: "DELETE", query: edge }),
      subgraph: (filter: { label?: string; limit?: number } = {}) =>
        request<Subgraph>(`${base}/graph/subgraph`, { query: filter }),
      loadDemo: () =>
        request<{ loaded: Record<string, JsonObject> }>(`${base}/graph/demo`, { method: "POST" }),
      link: () => request<LinkResult>(`${base}/graph/link`, { method: "POST" }),
      linkScore: () => request<LinkScore>(`${base}/graph/link/score`),
      linkReview: () => request<LinkReviewRow[]>(`${base}/graph/link/review`),
      acceptLink: (edge: { src: string; type: string; dst: string }) =>
        request<GraphEdge>(`${base}/graph/link/review/accept`, { method: "POST", body: edge }),
      query: (cypher: string, params: JsonObject = {}) =>
        request<{ rows: JsonObject[] }>(`${base}/graph/query`, {
          method: "POST",
          body: { cypher, params },
        }),
    },
  };
}

export type WorkspaceApi = ReturnType<typeof workspaceApi>;
