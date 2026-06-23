/** Incident swimlane view (lazy route /graph).
 *  X = time, ONE LANE PER INCIDENT (title), member alerts as pills inside.
 *  Manual refresh by design — to enable polling, see
 *  src/features/graph/config.ts (GRAPH_REFRESH_INTERVAL_MS). */

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LoadingSpinner } from "@/components/common/loading-spinner";
import { SeverityBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SegmentedToggle } from "@/components/ui/segmented-toggle";
import { GRAPH_DEFAULT_WINDOW_HOURS } from "@/features/graph/config";
import { SwimlaneChart } from "@/features/graph/swimlane-chart";
import { useGraphData } from "@/features/graph/use-graph-data";
import { formatDate } from "@/lib/utils";
import type { GraphIncident } from "@/types";

const EMPTY: GraphIncident[] = [];

export default function GraphPage() {
  const { t } = useTranslation();
  const [windowHours, setWindowHours] = useState(GRAPH_DEFAULT_WINDOW_HOURS);
  const [selected, setSelected] = useState<GraphIncident | null>(null);

  const graph = useGraphData(windowHours);
  const data = graph.data?.data ?? { incidents: EMPTY, meta: { truncated: false, total_incidents: 0 } };

  // keep the selected incident's data fresh across refetches
  const selectedLive =
    selected && data.incidents.find((i) => i.id === selected.id)
      ? data.incidents.find((i) => i.id === selected.id)!
      : selected;

  return (
    <div className="flex h-full flex-col" data-testid="graph-page">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h1 className="mr-auto text-2xl font-semibold tracking-tight">{t("graph.title")}</h1>
        <SegmentedToggle
          size="sm"
          aria-label={t("graph.title")}
          value={String(windowHours)}
          onValueChange={(v) => setWindowHours(Number(v))}
          options={[
            { value: "24", label: "24h" },
            { value: "72", label: "3d" },
            { value: "168", label: "7d" },
          ]}
        />
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

      {data.meta.truncated && (
        <p className="mb-2 text-sm text-severity-warning">{t("graph.truncated")}</p>
      )}

      <div className="relative min-h-0 flex-1 overflow-hidden rounded-xl border border-border/60 bg-card">
        {graph.isLoading ? (
          <LoadingSpinner />
        ) : (
          <SwimlaneChart data={data} selectedId={selected?.id ?? null} onSelect={setSelected} />
        )}

        {/* legend — severity only (no edges in the incident-centric model) */}
        <div className="pointer-events-none absolute bottom-3 left-3 rounded-md bg-background/80 p-2 text-xs backdrop-blur">
          <div className="flex items-center gap-3">
            {(["critical", "warning", "info"] as const).map((sev) => (
              <span key={sev} className="flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: `hsl(var(--sev-${sev}))` }}
                />{" "}
                {sev}
              </span>
            ))}
          </div>
          <div className="mt-1 text-muted-foreground">{t("graph.legendLane")}</div>
        </div>

        {/* selection panel */}
        {selectedLive && (
          <Card
            className="absolute right-3 top-3 w-80 bg-background/95 backdrop-blur"
            data-testid="graph-detail"
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{selectedLive.title}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-xs">
              <div className="flex flex-wrap gap-1">
                <SeverityBadge severity={selectedLive.severity} />
                <Badge variant="outline">{selectedLive.status}</Badge>
                {selectedLive.cmdb_service_l2_code && (
                  <Badge variant="secondary">{selectedLive.cmdb_service_l2_code}</Badge>
                )}
              </div>
              <p className="text-muted-foreground">
                {t("ops.alerts")}: {selectedLive.alert_count} ·{" "}
                {formatDate(selectedLive.first_seen)} → {formatDate(selectedLive.last_seen)}
              </p>
              <div>
                <p className="mb-1 font-semibold">{t("graph.memberAlerts")}</p>
                <div className="max-h-52 space-y-1 overflow-y-auto">
                  {selectedLive.alerts.map((alert) => (
                    <div
                      key={alert.id}
                      className="flex items-center justify-between gap-2 rounded-md border border-border/60 px-2 py-1"
                    >
                      <span className="min-w-0 truncate">
                        <span className="font-medium">{alert.name}</span>
                        {alert.cmdb_hostname && (
                          <span className="ml-1 font-mono text-muted-foreground">
                            {alert.cmdb_hostname}
                          </span>
                        )}
                        {alert.dedup_count > 1 && (
                          <span className="ml-1 text-muted-foreground">×{alert.dedup_count}</span>
                        )}
                      </span>
                      <SeverityBadge severity={alert.severity} />
                    </div>
                  ))}
                  {selectedLive.alerts.length === 0 && (
                    <p className="text-muted-foreground">{t("graph.noAlerts")}</p>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
