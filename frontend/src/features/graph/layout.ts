/** Node positioning. Two layouts:
 *  - "time":  Z axis = first_seen (layout B, default) — cascades become shapes
 *  - "force": full 3D force-directed (layout A)
 *  The simulation runs synchronously on load (node counts are API-capped),
 *  then positions are frozen — no per-frame physics. */

import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  forceZ,
  type SimLink,
  type SimNode,
} from "d3-force-3d";

import type { GraphData, GraphNode } from "@/types";

export type LayoutMode = "time" | "force";

export interface PositionedNode extends GraphNode {
  x: number;
  y: number;
  z: number;
}

const Z_RANGE = 120; // time axis span (world units)
const HOST_RING_RADIUS = 70;

export function computeLayout(data: GraphData, mode: LayoutMode): PositionedNode[] {
  const hosts = data.nodes.filter((n) => n.kind === "host");
  const incidents = data.nodes.filter((n) => n.kind === "incident");

  // host anchors on a fixed ring -> stable landmarks across refreshes
  const hostPos = new Map<string, { x: number; y: number }>();
  hosts.forEach((host, i) => {
    const angle = (2 * Math.PI * i) / Math.max(hosts.length, 1);
    hostPos.set(host.id, {
      x: HOST_RING_RADIUS * Math.cos(angle),
      y: HOST_RING_RADIUS * Math.sin(angle),
    });
  });

  // time normalization for the Z axis
  const times = incidents
    .map((n) => (n.first_seen ? new Date(n.first_seen).getTime() : 0))
    .filter(Boolean);
  const tMin = Math.min(...(times.length ? times : [0]));
  const tMax = Math.max(...(times.length ? times : [1]));
  const tSpan = Math.max(tMax - tMin, 1);
  const zOf = (n: GraphNode) =>
    n.first_seen
      ? ((new Date(n.first_seen).getTime() - tMin) / tSpan - 0.5) * Z_RANGE
      : 0;

  const simNodes: SimNode[] = data.nodes.map((n) => {
    const anchor = n.kind === "host" ? hostPos.get(n.id) : undefined;
    return {
      ...n,
      x: anchor?.x ?? (Math.random() - 0.5) * 40,
      y: anchor?.y ?? (Math.random() - 0.5) * 40,
      z: mode === "time" ? zOf(n) : (Math.random() - 0.5) * 40,
      fx: anchor?.x ?? null,
      fy: anchor?.y ?? null,
      fz: mode === "time" ? (n.kind === "host" ? 0 : zOf(n)) : anchor ? 0 : null,
    };
  });
  const simLinks: SimLink[] = data.edges.map((e) => ({ ...e }));

  const sim = forceSimulation(simNodes, 3)
    .force(
      "link",
      forceLink(simLinks)
        .id((n) => n.id as string)
        .distance((l: SimLink) => (l.kind === "host" ? 25 : 40))
        .strength((l: SimLink) => ((l.weight as number) ?? 0.5) * 0.6),
    )
    .force("charge", forceManyBody().strength(-30))
    .force("collide", forceCollide(4))
    .force("x", forceX(0).strength(0.02))
    .force("y", forceY(0).strength(0.02));
  if (mode === "force") {
    sim.force("z", forceZ(0).strength(0.02));
  }
  sim.alpha(1).tick(200).stop();

  return simNodes as unknown as PositionedNode[];
}
