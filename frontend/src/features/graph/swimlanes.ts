/** Pure layout logic for the 2D swimlane graph (no DOM).
 *
 *  One horizontal lane per host (group_key), sorted noisiest-first.
 *  Incidents become time-positioned pills; overlapping pills stack into
 *  sub-rows. Lanes beyond `maxVisibleLanes` collapse behind a "+N hosts"
 *  expander. Temporal edges connect pills as undirected arcs — they mean
 *  "fired close together", never causality. same_name partners are
 *  resolved here so the chart can highlight them on hover/select.
 */

import type { GraphData, GraphNode } from "@/types";

export interface LanePill {
  node: GraphNode;
  /** sub-row inside the lane when time ranges overlap */
  row: number;
  startMs: number;
  endMs: number;
}

export interface Lane {
  host: string;
  pills: LanePill[];
  rowCount: number;
}

export interface TemporalEdge {
  source: GraphNode;
  target: GraphNode;
  weight: number;
}

export interface SwimlaneModel {
  lanes: Lane[];
  hiddenLaneCount: number;
  /** [min first_seen, max last_seen] over all incidents, ms epoch */
  domain: [number, number];
  /** temporal edges whose both endpoints sit in a visible lane */
  temporalEdges: TemporalEdge[];
  /** incident id -> ids correlated via same_name edges */
  sameNamePartners: Map<string, Set<string>>;
}

export interface SwimlaneOptions {
  maxVisibleLanes: number;
  expanded: boolean;
  /** pills closer than this (ms) stack into separate rows so neither is
   *  hidden once the renderer applies its minimum pixel width */
  minSeparationMs?: number;
}

const SEVERITY_RANK: Record<string, number> = { critical: 3, warning: 2, info: 1 };

function severityRank(node: GraphNode): number {
  return SEVERITY_RANK[node.severity ?? ""] ?? 0;
}

/** Greedy interval stacking: first row whose last pill ended early enough. */
function stackRows(pills: LanePill[], minSeparationMs: number): number {
  const rowEnds: number[] = [];
  for (const pill of pills) {
    let row = rowEnds.findIndex((end) => pill.startMs >= end + minSeparationMs);
    if (row === -1) {
      row = rowEnds.length;
      rowEnds.push(0);
    }
    pill.row = row;
    rowEnds[row] = Math.max(rowEnds[row], pill.endMs);
  }
  return Math.max(rowEnds.length, 1);
}

export function buildSwimlanes(
  data: GraphData,
  { maxVisibleLanes, expanded, minSeparationMs = 0 }: SwimlaneOptions,
): SwimlaneModel {
  const incidents = data.nodes.filter((n) => n.kind === "incident");

  const byHost = new Map<string, LanePill[]>();
  for (const node of incidents) {
    const startMs = node.first_seen ? Date.parse(node.first_seen) : 0;
    const endMs = node.last_seen ? Date.parse(node.last_seen) : startMs;
    const host = node.group_key ?? "";
    let pills = byHost.get(host);
    if (!pills) byHost.set(host, (pills = []));
    pills.push({ node, row: 0, startMs, endMs: Math.max(endMs, startMs) });
  }

  // noisiest lane first: incident count desc, then max severity desc, then name
  const allLanes: Lane[] = [...byHost.entries()]
    .map(([host, pills]) => {
      pills.sort((a, b) => a.startMs - b.startMs);
      return { host, pills, rowCount: stackRows(pills, minSeparationMs) };
    })
    .sort(
      (a, b) =>
        b.pills.length - a.pills.length ||
        Math.max(...b.pills.map((p) => severityRank(p.node))) -
          Math.max(...a.pills.map((p) => severityRank(p.node))) ||
        a.host.localeCompare(b.host),
    );

  const lanes = expanded ? allLanes : allLanes.slice(0, maxVisibleLanes);
  const hiddenLaneCount = allLanes.length - lanes.length;

  let min = Infinity;
  let max = -Infinity;
  for (const lane of allLanes) {
    for (const pill of lane.pills) {
      if (pill.startMs < min) min = pill.startMs;
      if (pill.endMs > max) max = pill.endMs;
    }
  }
  if (!Number.isFinite(min)) {
    const now = Date.now();
    min = now - 1;
    max = now;
  }
  if (min === max) max = min + 1;

  const visibleIds = new Set(
    lanes.flatMap((lane) => lane.pills.map((p) => p.node.id)),
  );
  const nodeById = new Map(incidents.map((n) => [n.id, n]));

  const temporalEdges: TemporalEdge[] = [];
  const sameNamePartners = new Map<string, Set<string>>();
  for (const edge of data.edges) {
    if (edge.kind === "temporal") {
      const source = nodeById.get(edge.source);
      const target = nodeById.get(edge.target);
      if (source && target && visibleIds.has(source.id) && visibleIds.has(target.id)) {
        temporalEdges.push({ source, target, weight: edge.weight });
      }
    } else if (edge.kind === "same_name") {
      let a = sameNamePartners.get(edge.source);
      if (!a) sameNamePartners.set(edge.source, (a = new Set()));
      a.add(edge.target);
      let b = sameNamePartners.get(edge.target);
      if (!b) sameNamePartners.set(edge.target, (b = new Set()));
      b.add(edge.source);
    }
  }

  return { lanes, hiddenLaneCount, domain: [min, max], temporalEdges, sameNamePartners };
}
