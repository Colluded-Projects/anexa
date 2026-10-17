import { describe, expect, it } from "vitest";
import { forceLayout, viewBoxFor } from "./force";

const distance = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  Math.hypot(a.x - b.x, a.y - b.y);

describe("forceLayout", () => {
  it("handles empty and single-node graphs", () => {
    expect(forceLayout([], []).size).toBe(0);
    expect(forceLayout(["a"], [], { width: 100, height: 50 }).get("a")).toEqual({ x: 50, y: 25 });
  });

  it("gives every node a distinct, finite position", () => {
    const ids = Array.from({ length: 40 }, (_, i) => `n${i}`);
    const edges = ids.slice(1).map((id, i) => ({ src: ids[i] as string, dst: id }));
    const layout = forceLayout(ids, edges);
    const points = [...layout.values()];
    expect(points).toHaveLength(40);
    for (const point of points) {
      expect(Number.isFinite(point.x) && Number.isFinite(point.y)).toBe(true);
    }
    const unique = new Set(points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`));
    expect(unique.size).toBe(40);
  });

  it("is deterministic", () => {
    const edges = [{ src: "a", dst: "b" }];
    expect([...forceLayout(["a", "b", "c"], edges)]).toEqual([...forceLayout(["a", "b", "c"], edges)]);
  });

  it("places linked nodes closer together than unlinked ones", () => {
    const layout = forceLayout(["a", "b", "c", "d"], [{ src: "a", dst: "b" }]);
    const ab = distance(layout.get("a")!, layout.get("b")!);
    const cd = distance(layout.get("c")!, layout.get("d")!);
    expect(ab).toBeLessThan(cd);
  });

  it("ignores edges that point at unknown nodes", () => {
    expect(forceLayout(["a", "b"], [{ src: "a", dst: "ghost" }]).size).toBe(2);
  });
});

describe("viewBoxFor", () => {
  it("pads the bounding box", () => {
    const box = viewBoxFor(
      new Map([
        ["a", { x: 0, y: 0 }],
        ["b", { x: 400, y: 300 }],
      ]),
      50,
    );
    expect(box).toEqual([-50, -50, 500, 400]);
  });
});
