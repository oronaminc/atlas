import { describe, expect, it } from "vitest";

import { buildSwimlanes } from "@/features/graph/swimlanes";
import type { GraphData, GraphNode } from "@/types";

const T0 = Date.parse("2026-06-12T00:00:00Z");

function incident(
  id: string,
  host: string,
  startMin: number,
  endMin: number,
  severity = "warning",
): GraphNode {
  return {
    id,
    kind: "incident",
    label: id,
    severity,
    status: "open",
    group_key: host,
    first_seen: new Date(T0 + startMin * 60_000).toISOString(),
    last_seen: new Date(T0 + endMin * 60_000).toISOString(),
  };
}

function data(nodes: GraphNode[], edges: GraphData["edges"] = []): GraphData {
  return { nodes, edges, meta: { truncated: false, total_incidents: nodes.length } };
}

describe("buildSwimlanes", () => {
  it("sorts lanes noisiest-first, severity breaks ties", () => {
    const model = buildSwimlanes(
      data([
        incident("a1", "quiet", 0, 10),
        incident("b1", "noisy", 0, 10),
        incident("b2", "noisy", 20, 30),
        incident("b3", "noisy", 40, 50),
        incident("c1", "hot", 0, 10, "critical"),
      ]),
      { maxVisibleLanes: 12, expanded: false },
    );
    expect(model.lanes.map((l) => l.host)).toEqual(["noisy", "hot", "quiet"]);
  });

  it("collapses tail lanes behind the expander and restores them when expanded", () => {
    const nodes = Array.from({ length: 15 }, (_, i) =>
      incident(`i${i}`, `host-${String(i).padStart(2, "0")}`, i, i + 5),
    );
    const collapsed = buildSwimlanes(data(nodes), { maxVisibleLanes: 12, expanded: false });
    expect(collapsed.lanes).toHaveLength(12);
    expect(collapsed.hiddenLaneCount).toBe(3);

    const expanded = buildSwimlanes(data(nodes), { maxVisibleLanes: 12, expanded: true });
    expect(expanded.lanes).toHaveLength(15);
    expect(expanded.hiddenLaneCount).toBe(0);
  });

  it("stacks overlapping pills into sub-rows, keeps disjoint pills on one row", () => {
    const model = buildSwimlanes(
      data([
        incident("a", "h", 0, 60),
        incident("b", "h", 30, 90), // overlaps a
        incident("c", "h", 120, 150), // disjoint -> back to row 0
      ]),
      { maxVisibleLanes: 12, expanded: false },
    );
    const rows = Object.fromEntries(
      model.lanes[0].pills.map((p) => [p.node.id, p.row]),
    );
    expect(rows).toEqual({ a: 0, b: 1, c: 0 });
    expect(model.lanes[0].rowCount).toBe(2);
  });

  it("stacks pills closer than minSeparationMs even without overlap", () => {
    const model = buildSwimlanes(
      data([incident("a", "h", 0, 1), incident("b", "h", 2, 3)]),
      { maxVisibleLanes: 12, expanded: false, minSeparationMs: 5 * 60_000 },
    );
    const rows = model.lanes[0].pills.map((p) => p.row);
    expect(new Set(rows).size).toBe(2);
  });

  it("drops temporal edges touching hidden lanes, keeps visible ones, resolves same_name partners both ways", () => {
    const nodes = [
      incident("v1", "host-a", 0, 10),
      incident("v2", "host-a", 5, 15),
      incident("v3", "host-b", 0, 10),
      incident("h1", "host-c", 0, 10),
    ];
    const model = buildSwimlanes(
      data(nodes, [
        { source: "v1", target: "v2", kind: "temporal", weight: 0.9 },
        { source: "v1", target: "h1", kind: "temporal", weight: 0.5 },
        { source: "v2", target: "v3", kind: "same_name", weight: 1 },
        { source: "v1", target: "host-a", kind: "host", weight: 1 },
      ]),
      { maxVisibleLanes: 2, expanded: false },
    );
    expect(model.lanes.map((l) => l.host)).toEqual(["host-a", "host-b"]);
    expect(model.temporalEdges).toHaveLength(1);
    expect(model.temporalEdges[0].source.id).toBe("v1");
    expect(model.sameNamePartners.get("v2")).toEqual(new Set(["v3"]));
    expect(model.sameNamePartners.get("v3")).toEqual(new Set(["v2"]));
  });

  it("returns a non-degenerate domain spanning first_seen..last_seen", () => {
    const model = buildSwimlanes(
      data([incident("a", "h", 0, 60), incident("b", "h", 30, 240)]),
      { maxVisibleLanes: 12, expanded: false },
    );
    expect(model.domain).toEqual([T0, T0 + 240 * 60_000]);

    const empty = buildSwimlanes(data([]), { maxVisibleLanes: 12, expanded: false });
    expect(empty.lanes).toHaveLength(0);
    expect(empty.domain[1]).toBeGreaterThan(empty.domain[0]);
  });
});
