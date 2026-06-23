/** Pure layout logic for the incident swimlane graph (no DOM).
 *
 *  One horizontal lane PER INCIDENT (the lane label is the incident title).
 *  Inside each lane, the incident's member alerts are time-positioned pills
 *  (x = received_at). Pills whose times collide stack into sub-rows so none is
 *  hidden once the renderer applies its minimum pixel width. Lanes beyond
 *  `maxVisibleLanes` collapse behind a "+N incidents" expander.
 *
 *  The old host-lane + temporal/same_name edge + node/edge model is GONE —
 *  the payload is now incident-centric (GraphIncident with member alerts).
 */

import type { GraphAlert, GraphData, GraphIncident } from "@/types";

export interface AlertPill {
  alert: GraphAlert;
  /** sub-row inside the lane when timestamps collide */
  row: number;
  atMs: number;
}

export interface Lane {
  incident: GraphIncident;
  pills: AlertPill[];
  rowCount: number;
}

export interface SwimlaneModel {
  lanes: Lane[];
  hiddenLaneCount: number;
  /** [min received_at, max received_at] over all alerts (ms epoch) */
  domain: [number, number];
}

export interface SwimlaneOptions {
  maxVisibleLanes: number;
  expanded: boolean;
  /** pills closer than this (ms) stack into separate rows */
  minSeparationMs?: number;
}

const SEVERITY_RANK: Record<string, number> = { critical: 3, warning: 2, info: 1 };

function severityRank(sev: string): number {
  return SEVERITY_RANK[sev] ?? 0;
}

/** Greedy stacking: first row whose last pill ended early enough. */
function stackRows(pills: AlertPill[], minSeparationMs: number): number {
  const rowEnds: number[] = [];
  for (const pill of pills) {
    let row = rowEnds.findIndex((end) => pill.atMs >= end + minSeparationMs);
    if (row === -1) {
      row = rowEnds.length;
      rowEnds.push(-Infinity);
    }
    pill.row = row;
    rowEnds[row] = pill.atMs;
  }
  return Math.max(rowEnds.length, 1);
}

export function buildSwimlanes(
  data: GraphData,
  { maxVisibleLanes, expanded, minSeparationMs = 0 }: SwimlaneOptions,
): SwimlaneModel {
  const incidents = data.incidents ?? [];

  const allLanes: Lane[] = incidents
    .map((incident) => {
      const pills: AlertPill[] = (incident.alerts ?? []).map((alert) => ({
        alert,
        row: 0,
        atMs: Date.parse(alert.received_at),
      }));
      pills.sort((a, b) => a.atMs - b.atMs);
      return { incident, pills, rowCount: stackRows(pills, minSeparationMs) };
    })
    // noisiest first: alert count desc, then incident severity desc, then title
    .sort(
      (a, b) =>
        b.incident.alert_count - a.incident.alert_count ||
        severityRank(b.incident.severity) - severityRank(a.incident.severity) ||
        a.incident.title.localeCompare(b.incident.title),
    );

  const lanes = expanded ? allLanes : allLanes.slice(0, maxVisibleLanes);
  const hiddenLaneCount = allLanes.length - lanes.length;

  let min = Infinity;
  let max = -Infinity;
  for (const lane of allLanes) {
    for (const pill of lane.pills) {
      if (Number.isFinite(pill.atMs)) {
        if (pill.atMs < min) min = pill.atMs;
        if (pill.atMs > max) max = pill.atMs;
      }
    }
    // fall back to the incident's own span when it has no member alerts
    const fs = Date.parse(lane.incident.first_seen);
    const ls = Date.parse(lane.incident.last_seen);
    if (Number.isFinite(fs)) min = Math.min(min, fs);
    if (Number.isFinite(ls)) max = Math.max(max, ls);
  }
  if (!Number.isFinite(min)) {
    const now = Date.now();
    min = now - 1;
    max = now;
  }
  if (min === max) max = min + 1;

  return { lanes, hiddenLaneCount, domain: [min, max] };
}
