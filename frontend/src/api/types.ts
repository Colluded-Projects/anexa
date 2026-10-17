// Shapes mirror docs/api.md.

export type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };

export type Role = "owner" | "member";

export interface User {
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  role: Role;
  created_at: string;
}

export interface AuthResult {
  access_token: string;
  token_type: "bearer";
  user: User;
  workspace?: Workspace;
}

export interface Me {
  user: User;
  workspaces: Workspace[];
}

export interface Member {
  user_id: string;
  email: string;
  name: string;
  role: Role;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  /** Only present in the response that creates the key. */
  key?: string;
}

export type FieldType = "string" | "text" | "number" | "boolean" | "select";

export interface FieldSpec {
  name: string;
  label: string;
  type: FieldType;
  required: boolean;
  secret: boolean;
  help: string;
  default: Json;
  options: string[];
  placeholder: string;
}

export interface OperationSpec {
  name: string;
  title: string;
  description: string;
  kind: "action" | "sync";
  params: FieldSpec[];
}

export interface ConnectorSpec {
  key: string;
  title: string;
  description: string;
  config_fields: FieldSpec[];
  operations: OperationSpec[];
}

export type ConnectionStatus = "untested" | "ok" | "error";

export interface Connection {
  id: string;
  name: string;
  connector: string;
  config: JsonObject;
  secret_fields: string[];
  status: ConnectionStatus;
  status_detail: string;
  created_at: string;
  updated_at: string;
}

export interface ConnectionInput {
  name?: string;
  connector?: string;
  config?: JsonObject;
  secrets?: Record<string, string | null>;
}

export interface ConnectionTest {
  ok: boolean;
  detail: string;
  identity: JsonObject;
}

export interface Action {
  id: string;
  name: string;
  description: string;
  connection_id: string;
  connection_name: string;
  connector: string;
  operation: string;
  params: JsonObject;
  created_at: string;
  updated_at: string;
}

export interface ActionInput {
  name: string;
  description?: string;
  connection_id: string;
  operation: string;
  params?: JsonObject;
}

export interface OperatorTask {
  key: string;
  action_id: string;
  params: JsonObject;
  continue_on_error: boolean;
}

export interface Operator {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  tasks: OperatorTask[];
  created_at: string;
  updated_at: string;
}

export interface OperatorInput {
  name: string;
  description?: string;
  tasks?: OperatorTask[];
  enabled?: boolean;
}

export interface Schedule {
  id: string;
  operator_id: string;
  operator_name: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  input: JsonObject;
  next_run_at: string | null;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduleInput {
  operator_id: string;
  cron: string;
  timezone?: string;
  enabled?: boolean;
  input?: JsonObject;
}

export type RunStatus = "queued" | "running" | "succeeded" | "failed";
export type RunKind = "action" | "operator";
export type TaskStatus = "pending" | "running" | "succeeded" | "failed" | "skipped";

export interface TaskResult {
  key: string;
  action_id: string;
  action_name: string;
  status: TaskStatus;
  output: JsonObject | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface Run {
  id: string;
  kind: RunKind;
  target_id: string;
  target_name: string;
  status: RunStatus;
  trigger: "manual" | "schedule" | "mcp" | "api";
  triggered_by: string | null;
  input: JsonObject;
  output: JsonObject | null;
  error: string | null;
  tasks: TaskResult[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export type AgentProvider = "claude_code" | "openrouter" | "jev" | "custom";

export interface Agent {
  id: string;
  name: string;
  description: string;
  provider: AgentProvider;
  model: string;
  instructions: string;
  action_ids: string[];
  operator_ids: string[];
  status: "not_connected";
  created_at: string;
  updated_at: string;
}

export type AgentInput = Partial<Omit<Agent, "id" | "status" | "created_at" | "updated_at">> & {
  name: string;
};

export interface Summary {
  counts: {
    connections: number;
    actions: number;
    operators: number;
    schedules: number;
    agents: number;
    runs: number;
  };
  runs_by_status: Record<RunStatus, number>;
  recent_runs: Run[];
  graph: Record<string, number>;
}

export interface Ontology {
  node_labels: Record<string, string>;
  edge_types: Record<string, string>;
}

export interface GraphNode {
  id: string;
  label: string;
  name: string;
  key: string;
  source: string;
  url: string | null;
  props: JsonObject;
  updated_at: string;
}

export interface GraphEdge {
  src: string;
  type: string;
  dst: string;
  props: JsonObject;
}

export interface GraphNodeDetail extends GraphNode {
  edges: GraphEdge[];
  neighbors: GraphNode[];
}

export interface Subgraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface LinkResult {
  strategy: string;
  links: Record<string, number>;
}

export interface LinkScoreRow {
  expected: number;
  found: number;
  correct: number;
  precision: number;
  recall: number;
}

export type LinkScore = Record<string, LinkScoreRow>;

export interface Expert {
  name: string;
  key: string;
  score: number;
}

export interface GraphStats {
  nodes: Record<string, number>;
  total_nodes: number;
  total_edges: number;
}
