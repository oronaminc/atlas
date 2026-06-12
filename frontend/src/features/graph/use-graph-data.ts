import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import {
  GRAPH_DEFAULT_STATUS,
  GRAPH_MAX_NODES,
  GRAPH_REFRESH_INTERVAL_MS,
} from "@/features/graph/config";
import type { GraphData } from "@/types";

export function useGraphData(windowHours: number, status: string = GRAPH_DEFAULT_STATUS) {
  return useQuery({
    queryKey: ["graph", windowHours, status],
    queryFn: () =>
      api.get<GraphData>("/graph", {
        window_hours: String(windowHours),
        status,
        max_nodes: String(GRAPH_MAX_NODES),
      }),
    // Manual refresh by default; see config.ts for how to enable polling.
    refetchInterval: GRAPH_REFRESH_INTERVAL_MS,
    refetchOnWindowFocus: false,
  });
}

export function useExpandIncident(incidentId: string | null) {
  return useQuery({
    queryKey: ["graph", "incident", incidentId],
    queryFn: () =>
      api.get<Pick<GraphData, "nodes" | "edges">>(`/graph/incident/${incidentId}`),
    enabled: !!incidentId,
  });
}
