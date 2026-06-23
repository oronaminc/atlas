import { describe, expect, it } from "vitest";

import { buildSwimlanes } from "@/features/graph/swimlanes";
import type { GraphAlert, GraphData, GraphIncident } from "@/types";

const T0 = Date.parse("2026-06-12T00:00:00Z");

function alert(id: string, atMin: number, severity = "warning"): GraphAlert {
  return {
    id,
    name: `alert-${id}`,
    severity,
    status: "open",
    received_at: new Date(T0 + atMin * 60_000).toISOString(),
    cmdb_hostname: `host-${id}`,
    dedup_count: 1,
  };
}

function incident(
  id: string,
  title: string,
  alerts: GraphAlert[],
  severity = "warning",
): GraphIncident {
  const times = alerts.map((a) => Date.parse(a.received_at));
  return {
    id,
    title,
    severity,
    status: "open",
    first_seen: new Date(Math.min(...times, T0)).toISOString(),
    last_seen: new Date(Math.max(...times, T0)).toISOString(),
    alert_count: alerts.length,
    cmdb_service_l2_code: "svc",
    alerts,
  };
}

function data(incidents: GraphIncident[]): GraphData {
  return { incidents, meta: { truncated: false, total_incidents: incidents.length } };
}

describe("buildSwimlanes (incident-centric)", () => {
  it("builds one lane per incident, sorted noisiest-first, severity breaks ties", () => {
    const model = buildSwimlanes(
      data([
        incident("quiet", "Quiet", [alert("q1", 0)]),
        incident("noisy", "Noisy", [alert("n1", 0), alert("n2", 20), alert("n3", 40)]),
        incident("hot", "Hot", [alert("h1", 0, "critical")], "critical"),
      ]),
      { maxVisibleLanes: 12, expanded: false },
    );
    expect(model.lanes.map((l) => l.incident.id)).toEqual(["noisy", "hot", "quiet"]);
    expect(model.lanes[0].pills).toHaveLength(3);
  });

  it("places each incident's member alerts as pills inside its lane", () => {
    const model = buildSwimlanes(
      data([incident("i1", "One", [alert("a", 0), alert("b", 30), alert("c", 60)])]),
      { maxVisibleLanes: 12, expanded: false },
    );
    expect(model.lanes).toHaveLength(1);
    expect(model.lanes[0].pills.map((p) => p.alert.id)).toEqual(["a", "b", "c"]);
  });

  it("collapses tail lanes behind the expander and restores them when expanded", () => {
    const incidents = Array.from({ length: 15 }, (_, i) =>
      // distinct alert counts so the sort is deterministic
      incident(
        `i${i}`,
        `Incident ${i}`,
        Array.from({ length: 15 - i }, (_, j) => alert(`i${i}-${j}`, j)),
      ),
    );
    const collapsed = buildSwimlanes(data(incidents), { maxVisibleLanes: 12, expanded: false });
    expect(collapsed.lanes).toHaveLength(12);
    expect(collapsed.hiddenLaneCount).toBe(3);

    const expanded = buildSwimlanes(data(incidents), { maxVisibleLanes: 12, expanded: true });
    expect(expanded.lanes).toHaveLength(15);
    expect(expanded.hiddenLaneCount).toBe(0);
  });

  it("stacks pills closer than minSeparationMs into separate sub-rows", () => {
    const model = buildSwimlanes(
      data([incident("i", "Tight", [alert("a", 0), alert("b", 1)])]),
      { maxVisibleLanes: 12, expanded: false, minSeparationMs: 5 * 60_000 },
    );
    const rows = model.lanes[0].pills.map((p) => p.row);
    expect(new Set(rows).size).toBe(2);
    expect(model.lanes[0].rowCount).toBe(2);
  });

  it("keeps well-separated pills on a single row", () => {
    const model = buildSwimlanes(
      data([incident("i", "Spread", [alert("a", 0), alert("b", 60), alert("c", 120)])]),
      { maxVisibleLanes: 12, expanded: false, minSeparationMs: 60_000 },
    );
    expect(model.lanes[0].rowCount).toBe(1);
    expect(model.lanes[0].pills.every((p) => p.row === 0)).toBe(true);
  });

  it("returns a non-degenerate domain spanning the member-alert times", () => {
    const model = buildSwimlanes(
      data([incident("i", "Span", [alert("a", 0), alert("b", 240)])]),
      { maxVisibleLanes: 12, expanded: false },
    );
    expect(model.domain).toEqual([T0, T0 + 240 * 60_000]);

    const empty = buildSwimlanes(data([]), { maxVisibleLanes: 12, expanded: false });
    expect(empty.lanes).toHaveLength(0);
    expect(empty.domain[1]).toBeGreaterThan(empty.domain[0]);
  });

  it("falls back to the incident span when it has no member alerts", () => {
    const inc = incident("i", "Empty", []);
    inc.first_seen = new Date(T0).toISOString();
    inc.last_seen = new Date(T0 + 100 * 60_000).toISOString();
    const model = buildSwimlanes(data([inc]), { maxVisibleLanes: 12, expanded: false });
    expect(model.lanes).toHaveLength(1);
    expect(model.lanes[0].pills).toHaveLength(0);
    expect(model.domain).toEqual([T0, T0 + 100 * 60_000]);
  });
});
