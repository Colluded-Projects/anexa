import { useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  errorMessage,
  type Expert,
  type GraphNode,
  type JsonObject,
  type LinkResult,
  type LinkReviewRow,
  type LinkScore,
  type Ontology,
} from "../api";
import { useWorkspace } from "../auth/AuthContext";
import { GraphCanvas, labelColor } from "../components/GraphCanvas";
import { JsonField } from "../components/JsonField";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  cx,
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
  Textarea,
} from "../components/ui";
import { formatRelative } from "../lib/format";
import { useAsync } from "../lib/hooks";
import { parseJsonObject, prettyJson } from "../lib/json";

type View = "map" | "list" | "query" | "linking";

function LabelDot({ label, labels }: { label: string; labels: string[] }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
      style={{ background: labelColor(label, labels) }}
    />
  );
}

// --- node create / edit ------------------------------------------------------

function NodeForm({
  ontology,
  node,
  onSaved,
  onClose,
}: {
  ontology: Ontology;
  node?: GraphNode;
  onSaved: (node: GraphNode) => void;
  onClose: () => void;
}) {
  const { api } = useWorkspace();
  const labels = Object.keys(ontology.node_labels);
  const [label, setLabel] = useState(node?.label ?? labels[0] ?? "");
  const [name, setName] = useState(node?.name ?? "");
  const [key, setKey] = useState("");
  const [propsText, setPropsText] = useState(
    node && Object.keys(node.props ?? {}).length ? prettyJson(node.props) : "",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parsed = parseJsonObject(propsText);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!parsed.ok) return;
    setBusy(true);
    setError(null);
    try {
      onSaved(
        node
          ? await api.graph.updateNode(node.id, { name: name.trim(), props: parsed.value })
          : await api.graph.createNode({
              label,
              name: name.trim(),
              ...(key.trim() ? { key: key.trim() } : {}),
              props: parsed.value,
            }),
      );
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={node ? `Edit ${node.name}` : "Add node"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Label" htmlFor="node-label" help={ontology.node_labels[label]}>
          <Select
            id="node-label"
            value={label}
            disabled={Boolean(node)}
            aria-describedby="node-label-help"
            onChange={(event) => setLabel(event.target.value)}
          >
            {labels.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
            {node && !labels.includes(node.label) && <option value={node.label}>{node.label}</option>}
          </Select>
        </Field>
        <Field label="Name" htmlFor="node-name" required>
          <Input id="node-name" value={name} onChange={(event) => setName(event.target.value)} required />
        </Field>
        {!node && (
          <Field
            label="Key"
            htmlFor="node-key"
            help="Optional stable identity, such as email:ada@acme.com. Generated when left blank."
          >
            <Input
              id="node-key"
              value={key}
              aria-describedby="node-key-help"
              onChange={(event) => setKey(event.target.value)}
            />
          </Field>
        )}
        <JsonField
          id="node-props"
          label="Properties"
          value={propsText}
          onChange={setPropsText}
          help="Optional JSON object of extra properties, such as title or rationale."
        />
        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim() || !parsed.ok || !label}>
            {node ? "Save changes" : "Add node"}
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}

// --- edge create -------------------------------------------------------------

function EdgeForm({
  ontology,
  node,
  onSaved,
  onClose,
}: {
  ontology: Ontology;
  node: GraphNode;
  onSaved: () => void;
  onClose: () => void;
}) {
  const { api } = useWorkspace();
  const types = Object.keys(ontology.edge_types);
  const [type, setType] = useState(types[0] ?? "");
  const [direction, setDirection] = useState<"out" | "in">("out");
  const [search, setSearch] = useState("");
  const [otherId, setOtherId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);
  const candidates = useAsync(() => api.graph.nodes({ q: query || undefined, limit: 50 }), [api, query]);
  const options = (candidates.data ?? []).filter((item) => item.id !== node.id);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.graph.createEdge(
        direction === "out"
          ? { src: node.id, type, dst: otherId }
          : { src: otherId, type, dst: node.id },
      );
      onSaved();
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Modal title={`Add edge for ${node.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Relationship" htmlFor="edge-type" help={ontology.edge_types[type]}>
          <Select
            id="edge-type"
            value={type}
            aria-describedby="edge-type-help"
            onChange={(event) => setType(event.target.value)}
          >
            {types.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Direction" htmlFor="edge-direction">
          <Select
            id="edge-direction"
            value={direction}
            onChange={(event) => setDirection(event.target.value as "out" | "in")}
          >
            <option value="out">
              {node.name} → {type} → other node
            </option>
            <option value="in">
              Other node → {type} → {node.name}
            </option>
          </Select>
        </Field>
        <Field label="Find the other node" htmlFor="edge-search">
          <Input
            id="edge-search"
            type="search"
            value={search}
            placeholder="Search by name"
            onChange={(event) => setSearch(event.target.value)}
          />
        </Field>
        <Field
          label="Other node"
          htmlFor="edge-other"
          error={candidates.error}
          help={
            candidates.loading
              ? "Searching…"
              : options.length === 0
                ? "No nodes match."
                : `${options.length} match(es)`
          }
        >
          <Select
            id="edge-other"
            value={otherId}
            aria-describedby="edge-other-help"
            onChange={(event) => setOtherId(event.target.value)}
          >
            <option value="">Choose a node…</option>
            {options.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} ({item.label})
              </option>
            ))}
          </Select>
        </Field>
        <ErrorNote message={error} />
        <FormActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!otherId || !type}>
            Add edge
          </Button>
        </FormActions>
      </form>
    </Modal>
  );
}

// --- selected node panel -----------------------------------------------------

function NodePanel({
  nodeId,
  ontology,
  onSelect,
  onClose,
  onChanged,
}: {
  nodeId: string;
  ontology: Ontology;
  onSelect: (id: string) => void;
  onClose: () => void;
  onChanged: (deleted?: boolean) => void;
}) {
  const { api } = useWorkspace();
  const labels = Object.keys(ontology.node_labels);
  const detail = useAsync(() => api.graph.node(nodeId), [api, nodeId]);
  const [editing, setEditing] = useState(false);
  const [addingEdge, setAddingEdge] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const node = detail.data;
  const names = new Map((node?.neighbors ?? []).map((item) => [item.id, item]));

  async function removeEdge(edge: { src: string; type: string; dst: string }) {
    setError(null);
    try {
      await api.graph.removeEdge(edge);
      await detail.reload();
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  async function removeNode() {
    setBusy(true);
    setError(null);
    try {
      await api.graph.removeNode(nodeId);
      onChanged(true);
    } catch (cause) {
      setError(errorMessage(cause));
      setBusy(false);
    }
  }

  return (
    <Card className="lg:sticky lg:top-6">
      <CardHeader
        title="Selected node"
        actions={
          <button
            type="button"
            onClick={onClose}
            aria-label="Close node details"
            className="rounded px-1.5 text-lg leading-none text-muted hover:bg-sunken hover:text-ink"
          >
            ×
          </button>
        }
      />
      <div className="space-y-4 p-4">
        {detail.loading && <Loading label="Loading node" />}
        <ErrorNote message={detail.error ?? (deleting ? null : error)} onRetry={() => void detail.reload()} />

        {node && (
          <>
            <div>
              <div className="flex items-center gap-2">
                <LabelDot label={node.label} labels={labels} />
                <span className="text-xs text-muted">{node.label}</span>
              </div>
              <h2 className="mt-1 text-base font-semibold break-words">{node.name}</h2>
              {node.url && (
                <a
                  href={node.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="text-xs break-all text-accent underline"
                >
                  {node.url}
                </a>
              )}
            </div>

            <dl className="space-y-1.5 text-xs">
              {(
                [
                  ["Key", node.key],
                  ["Source", node.source],
                  ["Updated", formatRelative(node.updated_at)],
                ] as const
              ).map(([term, value]) => (
                <div key={term} className="flex gap-2">
                  <dt className="w-16 shrink-0 text-muted">{term}</dt>
                  <dd className="min-w-0 break-all text-ink">{value || "—"}</dd>
                </div>
              ))}
              {Object.entries(node.props ?? {}).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <dt className="w-16 shrink-0 truncate text-muted" title={key}>
                    {key}
                  </dt>
                  <dd className="min-w-0 break-words text-ink">
                    {typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}
                  </dd>
                </div>
              ))}
            </dl>

            <div>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">
                Edges ({node.edges.length})
              </h3>
              {node.edges.length === 0 ? (
                <p className="text-xs text-muted">Not connected to anything yet.</p>
              ) : (
                <ul className="space-y-1.5">
                  {node.edges.map((edge) => {
                    const outgoing = edge.src === node.id;
                    const otherId = outgoing ? edge.dst : edge.src;
                    const other = names.get(otherId);
                    return (
                      <li
                        key={`${edge.src}|${edge.type}|${edge.dst}`}
                        className="flex items-center gap-2 text-xs"
                      >
                        <span className="shrink-0 font-mono text-muted">
                          {outgoing ? "→" : "←"} {edge.type}
                        </span>
                        <button
                          type="button"
                          onClick={() => onSelect(otherId)}
                          className="min-w-0 truncate text-left text-accent underline"
                        >
                          {other?.name ?? otherId}
                        </button>
                        {typeof edge.props.method === "string" && (
                          <span
                            className="shrink-0 rounded bg-accent-soft px-1 text-accent"
                            title={typeof edge.props.evidence === "string" ? edge.props.evidence : undefined}
                          >
                            {edge.props.method} · {String(edge.props.confidence)}
                          </span>
                        )}
                        <button
                          type="button"
                          onClick={() => void removeEdge(edge)}
                          aria-label={`Remove ${edge.type} edge ${outgoing ? "to" : "from"} ${other?.name ?? otherId}`}
                          className="ml-auto shrink-0 rounded px-1 text-muted hover:bg-danger-soft hover:text-danger"
                        >
                          ×
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>

            <div className="flex flex-wrap gap-1.5 border-t border-line pt-4">
              <Button size="sm" onClick={() => setAddingEdge(true)}>
                Add edge
              </Button>
              <Button size="sm" onClick={() => setEditing(true)}>
                Edit
              </Button>
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  setError(null);
                  setDeleting(true);
                }}
              >
                Delete
              </Button>
            </div>
          </>
        )}
      </div>

      {node && editing && (
        <NodeForm
          ontology={ontology}
          node={node}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            void detail.reload();
            onChanged();
          }}
        />
      )}
      {node && addingEdge && (
        <EdgeForm
          ontology={ontology}
          node={node}
          onClose={() => setAddingEdge(false)}
          onSaved={() => {
            setAddingEdge(false);
            void detail.reload();
            onChanged();
          }}
        />
      )}
      {node && deleting && (
        <ConfirmDialog
          title={`Delete ${node.name}?`}
          busy={busy}
          error={error}
          onCancel={() => setDeleting(false)}
          onConfirm={() => void removeNode()}
        >
          The node and its {node.edges.length} edge(s) are removed from the company graph. A later sync
          may add it back.
        </ConfirmDialog>
      )}
    </Card>
  );
}

// --- cypher ------------------------------------------------------------------

function cell(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function CypherBox() {
  const { api } = useWorkspace();
  const [cypher, setCypher] = useState("MATCH (p:Person)-[r]->(n) RETURN p.name, type(r), n.name LIMIT 25");
  const [rows, setRows] = useState<JsonObject[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unsupported, setUnsupported] = useState(false);

  async function run(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setUnsupported(false);
    try {
      setRows((await api.graph.query(cypher)).rows);
    } catch (cause) {
      setRows(null);
      if (cause instanceof ApiError && cause.status === 501) setUnsupported(true);
      else if (cause instanceof ApiError && cause.status === 422) setError(`Query error: ${cause.message}`);
      else setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  const columns = rows ? [...new Set(rows.flatMap((row) => Object.keys(row)))] : [];

  return (
    <div className="space-y-4">
      <form onSubmit={run} className="space-y-3">
        <Field
          label="Cypher query"
          htmlFor="cypher"
          help="Read-only. Runs against this workspace's company graph."
        >
          <Textarea
            id="cypher"
            mono
            rows={4}
            value={cypher}
            aria-describedby="cypher-help"
            onChange={(event) => setCypher(event.target.value)}
          />
        </Field>
        <Button type="submit" variant="primary" busy={busy} disabled={!cypher.trim()}>
          Run query
        </Button>
      </form>

      <ErrorNote message={error} />
      {unsupported && (
        <Note>
          Cypher queries need the FalkorDB backend. This server is running on the in-memory store, so
          use the map and list views instead.
        </Note>
      )}
      {rows && rows.length === 0 && <Note>The query returned no rows.</Note>}
      {rows && rows.length > 0 && (
        <>
          <p className="text-xs text-muted">{rows.length} row(s)</p>
          <Table head={columns}>
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((column) => (
                  <Td key={column} className="max-w-xs font-mono text-xs break-words">
                    {cell(row[column])}
                  </Td>
                ))}
              </tr>
            ))}
          </Table>
        </>
      )}
    </div>
  );
}

export function LinkingPanel({ onChange }: { onChange?: () => void }) {
  const { api } = useWorkspace();
  const [busy, setBusy] = useState<"demo" | "link" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<LinkResult | null>(null);
  const [score, setScore] = useState<LinkScore | null>(null);
  const [review, setReview] = useState<LinkReviewRow[] | null>(null);

  async function decide(row: LinkReviewRow, accept: boolean) {
    setError(null);
    const edge = { src: row.src, type: row.type, dst: row.dst };
    try {
      if (accept) await api.graph.acceptLink(edge);
      else await api.graph.removeEdge(edge);
      setReview(await api.graph.linkReview());
      setScore(await api.graph.linkScore());
      onChange?.();
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  const [topic, setTopic] = useState("");
  const [experts, setExperts] = useState<Expert[] | null>(null);

  async function findExperts(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setExperts(await api.graph.experts(topic.trim()));
    } catch (cause) {
      setError(errorMessage(cause));
    }
  }

  async function run(what: "demo" | "link") {
    setBusy(what);
    setError(null);
    try {
      if (what === "demo") {
        const { loaded } = await api.graph.loadDemo();
        setMessage(`Loaded demo company from ${Object.keys(loaded).join(", ")}.`);
      } else {
        setResult(await api.graph.link());
      }
      setScore(await api.graph.linkScore());
      setReview(await api.graph.linkReview());
      onChange?.();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4">
      <Note>
        The linker connects what each connector wrote separately: the same person across systems,
        items that reference or talk about each other, and decisions. The score compares the links
        against the known-correct links of the demo company.
      </Note>
      <div className="flex gap-2">
        <Button busy={busy === "demo"} onClick={() => void run("demo")}>
          Load demo company
        </Button>
        <Button variant="primary" busy={busy === "link"} onClick={() => void run("link")}>
          Run linker
        </Button>
      </div>
      <ErrorNote message={error} />
      {message && <p className="text-sm text-muted">{message}</p>}
      {result && (
        <div className="text-sm">
          <p className="font-medium">Strategy: {result.strategy}</p>
          <p className="text-muted">{`LLM: ${result.llm}`}</p>
          <ul className="mt-1 flex flex-wrap gap-2 font-mono text-xs">
            {Object.entries(result.links).map(([type, count]) => (
              <li key={type}>{`${type}: ${count}`}</li>
            ))}
          </ul>
        </div>
      )}
      {score && (
        <Table head={["Category", "Expected", "Found", "Correct", "Precision", "Recall"]}>
          {Object.entries(score).map(([name, row]) => (
            <tr key={name}>
              <Td>{name}</Td>
              <Td>{row.expected}</Td>
              <Td>{row.found}</Td>
              <Td>{row.correct}</Td>
              <Td>{row.precision}</Td>
              <Td>{row.recall}</Td>
            </tr>
          ))}
        </Table>
      )}
      {review && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Review</h3>
          {review.length === 0 ? (
            <p className="text-sm text-muted">Nothing to review.</p>
          ) : (
            <ul className="space-y-2">
              {review.map((row) => {
                const label = `${row.src_name} ${row.type} ${row.dst_name}`;
                return (
                  <li key={`${row.src}-${row.type}-${row.dst}`} className="flex items-start gap-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p>
                        {row.src_name} <span className="font-mono text-xs">{row.type}</span> {row.dst_name}
                      </p>
                      <p className="text-xs text-muted">{`${row.method} · ${row.confidence}`}</p>
                      {row.evidence && <p className="text-xs text-muted">{row.evidence}</p>}
                    </div>
                    <Button aria-label={`Accept ${label}`} onClick={() => void decide(row, true)}>
                      Accept
                    </Button>
                    <Button aria-label={`Reject ${label}`} onClick={() => void decide(row, false)}>
                      Reject
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
      <form onSubmit={findExperts} className="flex items-end gap-2">
        <Field label="Who knows about…" htmlFor="expert-topic">
          <Input
            id="expert-topic"
            placeholder="kafka"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
          />
        </Field>
        <Button type="submit" disabled={!topic.trim()}>
          Find experts
        </Button>
      </form>
      {experts && (
        <ul className="text-sm">
          {experts.length === 0 && <li className="text-muted">Nobody yet.</li>}
          {experts.map((expert) => (
            <li key={expert.key}>{`${expert.name} (${expert.score})`}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

// --- page --------------------------------------------------------------------

export function GraphPage() {
  const { api } = useWorkspace();
  const [view, setView] = useState<View>("map");
  const [label, setLabel] = useState("");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const ontology = useAsync(() => api.graph.ontology(), [api]);
  const subgraph = useAsync(() => api.graph.subgraph({ label: label || undefined, limit: 200 }), [api, label]);
  const nodes = useAsync(
    () => api.graph.nodes({ label: label || undefined, q: query || undefined, limit: 200 }),
    [api, label, query],
  );

  const labels = Object.keys(ontology.data?.node_labels ?? {});

  function refresh(deleted?: boolean) {
    if (deleted) setSelectedId(null);
    void subgraph.reload();
    void nodes.reload();
  }

  const addButton = (
    <Button variant="primary" disabled={!ontology.data} onClick={() => setAdding(true)}>
      Add node
    </Button>
  );

  return (
    <>
      <PageHeader
        title="Company graph"
        description="People, teams, projects, documents, tickets and decisions, and how they connect. Sync actions keep it current; you can also edit it by hand."
        actions={addButton}
      />
      <ErrorNote message={ontology.error} className="mb-4" onRetry={() => void ontology.reload()} />

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div role="tablist" aria-label="Graph view" className="flex rounded-md border border-line-strong p-0.5">
          {(
            [
              ["map", "Map"],
              ["list", "List"],
              ["query", "Query"],
              ["linking", "Linking"],
            ] as const
          ).map(([value, text]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={view === value}
              onClick={() => setView(value)}
              className={cx(
                "rounded px-3 py-1.5 text-sm",
                view === value ? "bg-accent-soft font-medium text-accent" : "text-muted hover:text-ink",
              )}
            >
              {text}
            </button>
          ))}
        </div>

        {view !== "query" && (
          <div>
            <label htmlFor="graph-label" className="mb-1 block text-xs font-medium text-muted">
              Label
            </label>
            <Select id="graph-label" className="w-44!" value={label} onChange={(event) => setLabel(event.target.value)}>
              <option value="">All labels</option>
              {labels.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </div>
        )}
        {view === "list" && (
          <div className="min-w-48 flex-1 sm:max-w-xs">
            <label htmlFor="graph-search" className="mb-1 block text-xs font-medium text-muted">
              Search by name
            </label>
            <Input
              id="graph-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
        )}
      </div>

      {view === "linking" ? (
        <LinkingPanel onChange={() => refresh()} />
      ) : view === "query" ? (
        <CypherBox />
      ) : (
        <div className={cx("grid gap-5", selectedId && "lg:grid-cols-[minmax(0,1fr)_340px]")}>
          <div className="min-w-0">
            {view === "map" && (
              <>
                <ErrorNote message={subgraph.error} className="mb-4" onRetry={() => void subgraph.reload()} />
                {subgraph.loading ? (
                  <Loading label="Loading graph" />
                ) : (subgraph.data?.nodes.length ?? 0) === 0 && !subgraph.error ? (
                  <EmptyState title={label ? `No ${label} nodes` : "The graph is empty"} action={addButton}>
                    Run a sync action from a connection (for example GitHub or Slack) to pull in people
                    and projects, or add nodes by hand.
                  </EmptyState>
                ) : (
                  subgraph.data && (
                    <>
                      <GraphCanvas
                        nodes={subgraph.data.nodes}
                        edges={subgraph.data.edges}
                        labels={labels}
                        selectedId={selectedId}
                        onSelect={setSelectedId}
                      />
                      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted">
                        {labels
                          .filter((item) => subgraph.data?.nodes.some((node) => node.label === item))
                          .map((item) => (
                            <span key={item} className="flex items-center gap-1.5">
                              <LabelDot label={item} labels={labels} />
                              {item}
                            </span>
                          ))}
                        <span className="ml-auto">
                          {subgraph.data.nodes.length} nodes · {subgraph.data.edges.length} edges
                          {subgraph.data.nodes.length >= 200 && " (first 200 shown; filter by label to narrow)"}
                        </span>
                      </div>
                    </>
                  )
                )}
              </>
            )}

            {view === "list" && (
              <>
                <ErrorNote message={nodes.error} className="mb-4" onRetry={() => void nodes.reload()} />
                {nodes.loading ? (
                  <Loading label="Loading nodes" />
                ) : (nodes.data ?? []).length === 0 && !nodes.error ? (
                  <EmptyState title={query || label ? "No nodes match" : "The graph is empty"} action={addButton}>
                    {query || label ? "Try a different search or label." : "Add a node or run a sync action."}
                  </EmptyState>
                ) : (
                  <Table head={["Name", "Label", "Source", "Updated"]}>
                    {(nodes.data ?? []).map((node) => (
                      <tr key={node.id} className={cx(node.id === selectedId && "bg-accent-soft")}>
                        <Td>
                          <button
                            type="button"
                            onClick={() => setSelectedId(node.id)}
                            className="text-left font-medium text-accent underline"
                          >
                            {node.name || node.key}
                          </button>
                        </Td>
                        <Td>
                          <span className="flex items-center gap-2">
                            <LabelDot label={node.label} labels={labels} />
                            {node.label}
                          </span>
                        </Td>
                        <Td>
                          <Badge>{node.source || "unknown"}</Badge>
                        </Td>
                        <Td className="text-muted">{formatRelative(node.updated_at)}</Td>
                      </tr>
                    ))}
                  </Table>
                )}
              </>
            )}
          </div>

          {selectedId && ontology.data && (
            <NodePanel
              key={selectedId}
              nodeId={selectedId}
              ontology={ontology.data}
              onSelect={setSelectedId}
              onClose={() => setSelectedId(null)}
              onChanged={refresh}
            />
          )}
        </div>
      )}

      {adding && ontology.data && (
        <NodeForm
          ontology={ontology.data}
          onClose={() => setAdding(false)}
          onSaved={(node) => {
            setAdding(false);
            setSelectedId(node.id);
            refresh();
          }}
        />
      )}
    </>
  );
}
