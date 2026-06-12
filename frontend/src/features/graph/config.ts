/**
 * 2D swimlane graph refresh behavior.
 *
 * MANUAL refresh by design: the view is for deliberate investigation, not
 * passive monitoring (that's /ops).
 *
 * HOW TO SWITCH TO POLLING LATER:
 *   change GRAPH_REFRESH_INTERVAL_MS below from `false` to a number of
 *   milliseconds (e.g. 30_000). It is passed straight to TanStack Query's
 *   `refetchInterval` in `useGraphData` (src/features/graph/use-graph-data.ts).
 *   Nothing else needs to change — the swimlane layout is deterministic, so
 *   refreshes never shuffle lanes or pills the way a force sim would.
 */
export const GRAPH_REFRESH_INTERVAL_MS: number | false = false;

export const GRAPH_DEFAULT_WINDOW_HOURS = 24;
export const GRAPH_DEFAULT_STATUS = "open,acknowledged";
export const GRAPH_MAX_NODES = 2000;

/** lanes beyond this collapse behind the "+N hosts" expander */
export const GRAPH_MAX_VISIBLE_LANES = 12;
