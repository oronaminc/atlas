/**
 * 3D graph refresh behavior.
 *
 * MANUAL refresh by design: auto-polling re-runs the force layout and moves
 * nodes under the camera, which is disorienting in 3D.
 *
 * HOW TO SWITCH TO POLLING LATER:
 *   change GRAPH_REFRESH_INTERVAL_MS below from `false` to a number of
 *   milliseconds (e.g. 30_000). It is passed straight to TanStack Query's
 *   `refetchInterval` in `useGraphData` (src/features/graph/use-graph-data.ts).
 *   Nothing else needs to change — the layout already diffs by node id and
 *   keeps existing positions, so only new nodes get placed.
 */
export const GRAPH_REFRESH_INTERVAL_MS: number | false = false;

export const GRAPH_DEFAULT_WINDOW_HOURS = 24;
export const GRAPH_DEFAULT_STATUS = "open,acknowledged";
export const GRAPH_MAX_NODES = 2000;
