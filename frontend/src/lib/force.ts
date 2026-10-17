// A small deterministic force-directed layout: nodes repel each other, edges
// pull their endpoints together, and everything drifts towards the centre.
// Fine for the few hundred nodes the subgraph endpoint returns.

export interface Point {
  x: number;
  y: number;
}

export interface LayoutOptions {
  width?: number;
  height?: number;
  iterations?: number;
}

export function forceLayout(
  nodeIds: string[],
  edges: { src: string; dst: string }[],
  options: LayoutOptions = {},
): Map<string, Point> {
  const { width = 900, height = 600 } = options;
  const count = nodeIds.length;
  const positions = new Map<string, Point>();
  if (count === 0) return positions;

  const cx = width / 2;
  const cy = height / 2;
  if (count === 1) {
    positions.set(nodeIds[0] as string, { x: cx, y: cy });
    return positions;
  }

  const iterations = options.iterations ?? (count > 300 ? 120 : 300);
  const ideal = Math.sqrt((width * height) / count) * 0.8;
  const xs = new Float64Array(count);
  const ys = new Float64Array(count);
  const index = new Map<string, number>();

  // Start on a golden-angle spiral so the result is the same every time.
  nodeIds.forEach((id, i) => {
    index.set(id, i);
    const radius = ideal * 0.6 * Math.sqrt(i + 0.5);
    const angle = i * 2.399963229728653;
    xs[i] = cx + radius * Math.cos(angle);
    ys[i] = cy + radius * Math.sin(angle);
  });

  const links: [number, number][] = [];
  for (const edge of edges) {
    const a = index.get(edge.src);
    const b = index.get(edge.dst);
    if (a !== undefined && b !== undefined && a !== b) links.push([a, b]);
  }

  const dx = new Float64Array(count);
  const dy = new Float64Array(count);
  let temperature = Math.min(width, height) / 8;
  const cooling = temperature / (iterations + 1);

  for (let step = 0; step < iterations; step++) {
    dx.fill(0);
    dy.fill(0);

    for (let i = 0; i < count; i++) {
      for (let j = i + 1; j < count; j++) {
        let ox = (xs[i] as number) - (xs[j] as number);
        let oy = (ys[i] as number) - (ys[j] as number);
        let distance = Math.hypot(ox, oy);
        if (distance < 0.01) {
          ox = 0.01 * (i + 1);
          oy = 0.01 * (j + 1);
          distance = Math.hypot(ox, oy);
        }
        const force = (ideal * ideal) / distance;
        const fx = (ox / distance) * force;
        const fy = (oy / distance) * force;
        dx[i] = (dx[i] as number) + fx;
        dy[i] = (dy[i] as number) + fy;
        dx[j] = (dx[j] as number) - fx;
        dy[j] = (dy[j] as number) - fy;
      }
    }

    for (const [a, b] of links) {
      const ox = (xs[a] as number) - (xs[b] as number);
      const oy = (ys[a] as number) - (ys[b] as number);
      const distance = Math.max(0.01, Math.hypot(ox, oy));
      const force = (distance * distance) / ideal;
      const fx = (ox / distance) * force;
      const fy = (oy / distance) * force;
      dx[a] = (dx[a] as number) - fx;
      dy[a] = (dy[a] as number) - fy;
      dx[b] = (dx[b] as number) + fx;
      dy[b] = (dy[b] as number) + fy;
    }

    for (let i = 0; i < count; i++) {
      // Gentle pull to the centre keeps disconnected nodes from drifting away.
      const gx = (dx[i] as number) + (cx - (xs[i] as number)) * 0.06 * ideal * 0.1;
      const gy = (dy[i] as number) + (cy - (ys[i] as number)) * 0.06 * ideal * 0.1;
      const length = Math.max(0.01, Math.hypot(gx, gy));
      const move = Math.min(length, temperature);
      xs[i] = (xs[i] as number) + (gx / length) * move;
      ys[i] = (ys[i] as number) + (gy / length) * move;
    }
    temperature -= cooling;
  }

  nodeIds.forEach((id, i) => positions.set(id, { x: xs[i] as number, y: ys[i] as number }));
  return positions;
}

/** Bounding box of a layout, padded, as an SVG viewBox. */
export function viewBoxFor(positions: Map<string, Point>, padding = 60): [number, number, number, number] {
  if (positions.size === 0) return [0, 0, 900, 600];
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const point of positions.values()) {
    minX = Math.min(minX, point.x);
    minY = Math.min(minY, point.y);
    maxX = Math.max(maxX, point.x);
    maxY = Math.max(maxY, point.y);
  }
  return [
    minX - padding,
    minY - padding,
    Math.max(maxX - minX + padding * 2, 200),
    Math.max(maxY - minY + padding * 2, 150),
  ];
}
