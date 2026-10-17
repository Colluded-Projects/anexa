import { useMemo } from "react";
import type { GraphEdge, GraphNode } from "../api/types";
import { forceLayout, viewBoxFor } from "../lib/force";

// Categorical colours for node labels, chosen to stay distinguishable in both themes.
const PALETTE = ["#4f6bed", "#0f9d8a", "#d9822b", "#b0479b", "#7a8794", "#c7453d", "#5b8c2a", "#8a63d2"];

export function labelColor(label: string, labels: string[]): string {
  const index = labels.indexOf(label);
  return PALETTE[(index >= 0 ? index : labels.length) % PALETTE.length] as string;
}

interface GraphCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  labels: string[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function truncate(text: string, max = 22): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** SVG drawing of a subgraph. Nodes are keyboard-focusable buttons. */
export function GraphCanvas({ nodes, edges, labels, selectedId, onSelect }: GraphCanvasProps) {
  const layout = useMemo(
    () =>
      forceLayout(
        nodes.map((node) => node.id),
        edges,
      ),
    [nodes, edges],
  );
  const [minX, minY, width, height] = viewBoxFor(layout);
  const showEdgeLabels = edges.length <= 60;
  const showNodeLabels = nodes.length <= 120;

  const connected = useMemo(() => {
    if (!selectedId) return null;
    const ids = new Set([selectedId]);
    for (const edge of edges) {
      if (edge.src === selectedId) ids.add(edge.dst);
      if (edge.dst === selectedId) ids.add(edge.src);
    }
    return ids;
  }, [edges, selectedId]);

  return (
    <svg
      viewBox={`${minX} ${minY} ${width} ${height}`}
      role="group"
      aria-label={`Graph of ${nodes.length} nodes and ${edges.length} edges`}
      className="h-[520px] w-full rounded-lg border border-line bg-surface"
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--color-line-strong)" />
        </marker>
      </defs>

      <g>
        {edges.map((edge) => {
          const a = layout.get(edge.src);
          const b = layout.get(edge.dst);
          if (!a || !b) return null;
          const length = Math.max(1, Math.hypot(b.x - a.x, b.y - a.y));
          // Stop the line at the node's edge so the arrowhead stays visible.
          const ux = (b.x - a.x) / length;
          const uy = (b.y - a.y) / length;
          const active = selectedId !== null && (edge.src === selectedId || edge.dst === selectedId);
          return (
            <g key={`${edge.src}|${edge.type}|${edge.dst}`} opacity={selectedId && !active ? 0.25 : 1}>
              <line
                x1={a.x + ux * 12}
                y1={a.y + uy * 12}
                x2={b.x - ux * 14}
                y2={b.y - uy * 14}
                stroke={active ? "var(--color-accent)" : "var(--color-line-strong)"}
                strokeWidth={active ? 1.8 : 1.2}
                markerEnd="url(#arrow)"
              />
              {(showEdgeLabels || active) && (
                <text
                  x={(a.x + b.x) / 2}
                  y={(a.y + b.y) / 2 - 4}
                  textAnchor="middle"
                  fontSize="9"
                  fill="var(--color-muted)"
                >
                  {edge.type}
                </text>
              )}
            </g>
          );
        })}
      </g>

      <g>
        {nodes.map((node) => {
          const point = layout.get(node.id);
          if (!point) return null;
          const selected = node.id === selectedId;
          const dimmed = connected !== null && !connected.has(node.id);
          return (
            <g
              key={node.id}
              transform={`translate(${point.x} ${point.y})`}
              role="button"
              tabIndex={0}
              aria-label={`${node.label}: ${node.name}`}
              aria-pressed={selected}
              opacity={dimmed ? 0.3 : 1}
              style={{ cursor: "pointer" }}
              onClick={() => onSelect(node.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(node.id);
                }
              }}
            >
              <circle
                r={selected ? 13 : 10}
                fill={labelColor(node.label, labels)}
                stroke={selected ? "var(--color-ink)" : "var(--color-surface)"}
                strokeWidth={selected ? 2.5 : 2}
              />
              {(showNodeLabels || selected || (connected?.has(node.id) ?? false)) && (
                <text
                  y={26}
                  textAnchor="middle"
                  fontSize="11"
                  fontWeight={selected ? 600 : 400}
                  fill="var(--color-ink)"
                  stroke="var(--color-surface)"
                  strokeWidth="3"
                  paintOrder="stroke"
                >
                  {truncate(node.name || node.key)}
                </text>
              )}
            </g>
          );
        })}
      </g>
    </svg>
  );
}
