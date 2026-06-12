/** 3D alert-relationship explorer (lazy route /graph).
 *  Manual refresh by design — to enable polling, see
 *  src/features/graph/config.ts (GRAPH_REFRESH_INTERVAL_MS). */

import { useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LoadingSpinner } from "@/components/common/loading-spinner";
import { SeverityBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GRAPH_DEFAULT_WINDOW_HOURS } from "@/features/graph/config";
import { computeLayout, type LayoutMode, type PositionedNode } from "@/features/graph/layout";
import { GraphScene } from "@/features/graph/scene";
import { useExpandIncident, useGraphData } from "@/features/graph/use-graph-data";
import { formatDate } from "@/lib/utils";

export default function GraphPage() {
  const { t } = useTranslation();
  const [windowHours, setWindowHours] = useState(GRAPH_DEFAULT_WINDOW_HOURS);
  const [mode, setMode] = useState<LayoutMode>("time");
  const [selected, setSelected] = useState<PositionedNode | null>(null);

  const graph = useGraphData(windowHours);
  const expansion = useExpandIncident(
    selected?.kind === "incident" ? selected.id : null,
  );

  const positioned = useMemo(
    () => (graph.data ? computeLayout(graph.data.data, mode) : []),
    [graph.data, mode],
  );

  return (
    <div className="flex h-full flex-col" data-testid="graph-page">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-2xl font-semibold tracking-tight">
          {t("graph.title")}
        </h1>
        <div className="flex gap-1">
          {[24, 72, 168].map((h) => (
            <Button
              key={h}
              size="sm"
              variant={windowHours === h ? "default" : "outline"}
              onClick={() => setWindowHours(h)}
            >
              {h === 24 ? "24h" : h === 72 ? "3d" : "7d"}
            </Button>
          ))}
        </div>
        <div className="flex gap-1">
          <Button
            size="sm"
            variant={mode === "time" ? "default" : "outline"}
            onClick={() => setMode("time")}
            data-testid="layout-time"
          >
            {t("graph.layoutTime")}
          </Button>
          <Button
            size="sm"
            variant={mode === "force" ? "default" : "outline"}
            onClick={() => setMode("force")}
            data-testid="layout-force"
          >
            {t("graph.layoutForce")}
          </Button>
        </div>
        {/* Manual refresh (no auto-poll): switch via config.ts if needed */}
        <Button
          size="sm"
          variant="outline"
          onClick={() => graph.refetch()}
          disabled={graph.isFetching}
          data-testid="graph-refresh"
        >
          <RefreshCw className={`h-4 w-4 ${graph.isFetching ? "animate-spin" : ""}`} />
          {t("graph.refresh")}
        </Button>
      </div>

      {graph.data?.data.meta.truncated && (
        <p className="mb-2 text-sm text-amber-500">{t("graph.truncated")}</p>
      )}

      <div className="relative min-h-0 flex-1 overflow-hidden rounded-lg border">
        {graph.isLoading ? (
          <LoadingSpinner />
        ) : (
          <GraphScene
            nodes={positioned}
            edges={graph.data?.data.edges ?? []}
            selectedId={selected?.id ?? null}
            onSelect={setSelected}
          />
        )}

        {/* legend */}
        <div className="absolute bottom-3 left-3 rounded-md bg-background/80 p-2 text-xs backdrop-blur">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-red-500" /> critical
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-amber-500" /> warning
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-full bg-blue-500" /> info
            </span>
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 bg-slate-500" /> host
            </span>
          </div>
          <div className="mt-1 flex items-center gap-3 text-muted-foreground">
            <span className="text-cyan-400">— temporal</span>
            <span className="text-violet-400">— same alert</span>
            {mode === "time" && <span>{t("graph.zAxis")}</span>}
          </div>
        </div>

        {/* selection panel */}
        {selected && (
          <Card
            className="absolute right-3 top-3 w-80 bg-background/95 backdrop-blur"
            data-testid="graph-detail"
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{selected.label}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex flex-wrap gap-1">
                {selected.severity && <SeverityBadge severity={selected.severity} />}
                {selected.status && <Badge variant="outline">{selected.status}</Badge>}
                {selected.group_key && (
                  <Badge variant="secondary">{selected.group_key}</Badge>
                )}
              </div>
              {selected.kind === "incident" && (
                <>
                  <p className="text-muted-foreground">
                    {t("ops.alerts")}: {selected.alert_count} ·{" "}
                    {formatDate(selected.first_seen ?? null)} →{" "}
                    {formatDate(selected.last_seen ?? null)}
                  </p>
                  <div>
                    <p className="mb-1 font-semibold">{t("graph.memberAlerts")}</p>
                    {expansion.isLoading ? (
                      <LoadingSpinner className="h-4 w-4" />
                    ) : (
                      <div className="max-h-44 space-y-1 overflow-y-auto">
                        {(expansion.data?.data.nodes ?? []).map((alert) => (
                          <div
                            key={alert.id}
                            className="flex items-center justify-between rounded border px-2 py-1"
                          >
                            <span>
                              {alert.label}
                              <span className="ml-1 text-muted-foreground">
                                {alert.source} ×{alert.dedup_count}
                              </span>
                            </span>
                            <SeverityBadge severity={alert.severity ?? "info"} />
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
