import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Activity, BellRing, Flame, Server } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  useApiMutation,
  useGroups,
  useIncident,
  useIncidentAnalysis,
  useIncidents,
  useNotificationRows,
  useStatsHosts,
  useStatsOverview,
  useStatsTrend,
  useTenants,
} from "@/api/queries";
import { api } from "@/api/client";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { SeverityBadge } from "@/components/common/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SegmentedToggle } from "@/components/ui/segmented-toggle";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TrendChart } from "@/features/ops/trend-chart";
import { AlertList, Timeline } from "@/features/ops/incident-detail";
import { formatDate } from "@/lib/utils";
import { stripGroupKey } from "@/lib/server-identity";
import type { IncidentStatus } from "@/types";

const ALL = "__all__";
// "active" = needs attention: excludes resolved AND suppressed
const ACTIVE = "open,acknowledged";

const incidentStatusVariant: Record<
  IncidentStatus,
  "critical" | "warning" | "success" | "secondary"
> = {
  open: "critical",
  acknowledged: "warning",
  resolved: "success",
  suppressed: "secondary",
};

const notificationStatusVariant: Record<string, "secondary" | "success" | "warning" | "destructive"> = {
  pending: "secondary",
  sent: "success",
  failed: "warning",
  dead: "destructive",
};

function StatCard({
  title,
  value,
  icon: Icon,
  tone,
}: {
  title: string;
  value: number | string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: string;
}) {
  return (
    <Card>
      <CardContent className="flex items-center justify-between p-5">
        <div className="space-y-1">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <p className="text-2xl font-semibold tabular-nums">{value}</p>
        </div>
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
          <Icon className={`h-5 w-5 ${tone ?? "text-muted-foreground"}`} />
        </div>
      </CardContent>
    </Card>
  );
}

export function OpsPage() {
  const { t } = useTranslation();
  const { hasRole, user: me } = useAuth();
  const canEdit = hasRole("admin", "editor");
  const isHq = me?.tenant_id == null;
  const [statusFilter, setStatusFilter] = useState(ACTIVE);
  const [tenantFilter, setTenantFilter] = useState(ALL);
  const tenants = useTenants();
  const tenantParam = isHq && tenantFilter !== ALL ? tenantFilter : undefined;
  const tenantSlugById = new Map((tenants.data?.data ?? []).map((x) => [x.id, x.slug]));
  const [trendHours, setTrendHours] = useState(24);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  useEffect(() => {
    const id = searchParams.get("incident");
    if (id) setDetailId(id);
  }, [searchParams]);

  const overview = useStatsOverview(tenantParam);
  // "Load more" grows the page size (API caps at 100). Reset when filters change
  // so a narrowed query starts from the top.
  const [incidentLimit, setIncidentLimit] = useState(20);
  useEffect(() => setIncidentLimit(20), [statusFilter, tenantFilter]);
  const incidents = useIncidents({
    limit: String(incidentLimit),
    status: statusFilter === ALL ? undefined : statusFilter,
    tenant: tenantParam,
  });
  const incidentsHasMore = incidents.data?.meta?.has_more ?? false;
  const notifications = useNotificationRows({ limit: "20" });
  const trend = useStatsTrend(trendHours, tenantParam);
  const hostStats = useStatsHosts(tenantParam);
  const detail = useIncident(detailId);
  const analysis = useIncidentAnalysis(detailId);
  const analyze = useApiMutation(
    ({ force }: { force?: boolean }) =>
      api.post(`/incidents/${detailId}/analyze${force ? "?force=true" : ""}`),
    ["incident-analysis"],
  );

  const { toast } = useToast();
  const groups = useGroups();
  const [notifyGroupId, setNotifyGroupId] = useState("");
  const action = useApiMutation(
    ({ verb, body }: { verb: string; body?: Record<string, unknown> }) =>
      api.post(`/incidents/${detailId}/${verb}`, body),
    ["incidents", "stats"],
    () => setNotifyGroupId(""),
  );
  const runAction = (verb: string, body?: Record<string, unknown>) =>
    action.mutate(
      { verb, body },
      {
        onError: (e) =>
          toast({
            title: t("ops.actionFailed"),
            description: e instanceof Error ? e.message : String(e),
            variant: "destructive",
          }),
      },
    );

  const ov = overview.data?.data;

  return (
    <div data-testid="ops-page">
      <PageHeader title={t("ops.title")} description={t("ops.description")} />

      {isHq && (
        <div className="mb-4 flex items-center gap-2">
          <span className="text-sm text-muted-foreground">{t("tenants.filterLabel")}</span>
          <Select value={tenantFilter} onValueChange={setTenantFilter}>
            <SelectTrigger className="h-8 w-44" data-testid="tenant-filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("tenants.allTenants")}</SelectItem>
              {(tenants.data?.data ?? []).map((tenant) => (
                <SelectItem key={tenant.slug} value={tenant.slug}>
                  {tenant.slug}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title={t("ops.openIncidents")}
          value={ov ? ov.incidents.open + ov.incidents.acknowledged : "-"}
          icon={Flame}
          tone="text-destructive"
        />
        <StatCard
          title={t("ops.criticalOpen")}
          value={ov?.open_by_severity.critical ?? "-"}
          icon={Activity}
          tone="text-destructive"
        />
        <StatCard
          title={t("ops.alerts24h")}
          value={ov?.alerts_24h ?? "-"}
          icon={Server}
        />
        <StatCard
          title={t("ops.failedNotifications")}
          value={ov ? ov.notifications.failed + ov.notifications.dead : "-"}
          icon={BellRing}
          tone="text-severity-warning"
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        {/* Panel 1: incidents */}
        <Card data-testid="panel-incidents">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">{t("ops.incidents")}</CardTitle>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-8 w-40" data-testid="incident-status-filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ACTIVE}>{t("ops.filterActive")}</SelectItem>
                <SelectItem value={ALL}>status: all</SelectItem>
                <SelectItem value="open">open</SelectItem>
                <SelectItem value="acknowledged">acknowledged</SelectItem>
                <SelectItem value="resolved">resolved</SelectItem>
                <SelectItem value="suppressed">suppressed</SelectItem>
              </SelectContent>
            </Select>
          </CardHeader>
          <CardContent>
            {incidents.isLoading ? (
              <LoadingSpinner />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("ops.incident")}</TableHead>
                    {isHq && <TableHead>{t("tenants.tenant")}</TableHead>}
                    <TableHead>{t("rules.severity")}</TableHead>
                    <TableHead>{t("ops.status")}</TableHead>
                    <TableHead className="text-right">{t("ops.alerts")}</TableHead>
                    <TableHead>{t("ops.lastSeen")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(incidents.data?.data ?? []).map((incident) => (
                    <TableRow
                      key={incident.id}
                      className="cursor-pointer"
                      onClick={() => setDetailId(incident.id)}
                    >
                      <TableCell>
                        <div className="font-medium">{incident.title}</div>
                        <div className="flex items-center gap-1 text-xs text-muted-foreground">
                          <Server className="h-3 w-3" />
                          {stripGroupKey(incident.group_key) || "—"}
                        </div>
                      </TableCell>
                      {isHq && (
                        <TableCell>
                          <Badge variant="outline">
                            {(incident.tenant_id && tenantSlugById.get(incident.tenant_id)) || "-"}
                          </Badge>
                        </TableCell>
                      )}
                      <TableCell>
                        <SeverityBadge severity={incident.severity} />
                      </TableCell>
                      <TableCell>
                        <Badge variant={incidentStatusVariant[incident.status]}>
                          {incident.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{incident.alert_count}</TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(incident.last_seen)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {incidentsHasMore && (
              <div className="mt-3 flex justify-center">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setIncidentLimit((n) => Math.min(n + 20, 100))}
                  data-testid="incidents-load-more"
                >
                  {t("ops.loadMore")}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Panel 2: notification delivery */}
        <Card data-testid="panel-notifications">
          <CardHeader>
            <CardTitle className="text-base">{t("ops.deliveryStatus")}</CardTitle>
          </CardHeader>
          <CardContent>
            {notifications.isLoading ? (
              <LoadingSpinner />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("ops.channel")}</TableHead>
                    <TableHead>{t("ops.recipient")}</TableHead>
                    <TableHead>{t("ops.status")}</TableHead>
                    <TableHead className="text-right">{t("ops.attempts")}</TableHead>
                    <TableHead>{t("ops.detailCol")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(notifications.data?.data ?? []).map((n) => (
                    <TableRow key={n.id}>
                      <TableCell>
                        <Badge variant="outline">{n.channel}</Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{n.recipient_address}</TableCell>
                      <TableCell>
                        <Badge variant={notificationStatusVariant[n.status] ?? "secondary"}>
                          {n.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{n.attempts}</TableCell>
                      <TableCell className="max-w-48 truncate text-xs text-muted-foreground">
                        {n.status === "sent"
                          ? formatDate(n.sent_at)
                          : n.last_error ?? (n.retry_at ? `retry ${formatDate(n.retry_at)}` : "-")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        {/* Panel 3: severity stats + trend */}
        <Card data-testid="panel-trend">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">{t("ops.trend")}</CardTitle>
            <SegmentedToggle
              size="sm"
              aria-label={t("ops.trend")}
              value={String(trendHours)}
              onValueChange={(v) => setTrendHours(Number(v))}
              options={[
                { value: "24", label: "24h" },
                { value: "168", label: "7d" },
              ]}
            />
          </CardHeader>
          <CardContent>
            <div className="mb-3 flex gap-4 text-sm">
              {ov &&
                (["critical", "warning", "info"] as const).map((severity) => (
                  <span key={severity} className="flex items-center gap-2">
                    <SeverityBadge severity={severity} />
                    <span className="font-semibold">{ov.open_by_severity[severity]}</span>
                  </span>
                ))}
            </div>
            {trend.isLoading ? (
              <LoadingSpinner />
            ) : (
              <TrendChart buckets={trend.data?.data.buckets ?? []} />
            )}
          </CardContent>
        </Card>

        {/* Panel 4: per-host */}
        <Card data-testid="panel-hosts">
          <CardHeader>
            <CardTitle className="text-base">{t("ops.byHost")}</CardTitle>
          </CardHeader>
          <CardContent>
            {hostStats.isLoading ? (
              <LoadingSpinner />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("ops.host")}</TableHead>
                    <TableHead className="text-right">{t("ops.openCol")}</TableHead>
                    <TableHead className="text-right">{t("ops.totalCol")}</TableHead>
                    <TableHead className="text-right">{t("ops.alerts")}</TableHead>
                    <TableHead>{t("rules.severity")}</TableHead>
                    <TableHead>{t("ops.lastSeen")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(hostStats.data?.data ?? []).map((h) => (
                    <TableRow key={h.group_key}>
                      <TableCell className="font-mono text-sm">{h.group_key}</TableCell>
                      <TableCell className="text-right font-semibold">{h.open}</TableCell>
                      <TableCell className="text-right">{h.total}</TableCell>
                      <TableCell className="text-right">{h.alerts}</TableCell>
                      <TableCell>
                        <SeverityBadge severity={h.max_severity} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(h.last_seen)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>

      {/* incident detail */}
      <Dialog open={!!detailId} onOpenChange={(open) => !open && setDetailId(null)}>
        <DialogContent className="max-h-[88vh] max-w-4xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{detail.data?.data.title ?? t("ops.incident")}</DialogTitle>
          </DialogHeader>
          {detail.isLoading || !detail.data ? (
            <LoadingSpinner />
          ) : (
            <div className="space-y-4" data-testid="incident-detail">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={detail.data.data.severity} />
                <Badge variant={incidentStatusVariant[detail.data.data.status]}>
                  {detail.data.data.status}
                </Badge>
                {detail.data.data.group_key && (
                  <Badge variant="outline">{detail.data.data.group_key}</Badge>
                )}
                <span className="text-xs text-muted-foreground">
                  {formatDate(detail.data.data.first_seen)} → {formatDate(detail.data.data.last_seen)}
                </span>
              </div>

              {/* actions: editor+ only (matches backend require_editor) */}
              {canEdit && detail.data.data.status !== "resolved" && (
                <div
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 bg-muted/30 p-2"
                  data-testid="incident-actions"
                >
                  {detail.data.data.status === "suppressed" ? (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={action.isPending}
                      onClick={() => runAction("unsuppress")}
                      data-testid="action-unsuppress"
                    >
                      {t("ops.unsuppress")}
                    </Button>
                  ) : (
                    <>
                      {detail.data.data.status === "open" && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={action.isPending}
                          onClick={() => runAction("ack")}
                          data-testid="action-ack"
                        >
                          {t("ops.ack")}
                        </Button>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={action.isPending}
                        onClick={() => runAction("suppress")}
                        data-testid="action-suppress"
                      >
                        {t("ops.suppress")}
                      </Button>
                    </>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={action.isPending}
                    onClick={() => runAction("resolve")}
                    data-testid="action-resolve"
                  >
                    {t("ops.resolve")}
                  </Button>
                  <div className="flex items-center gap-1">
                    <Select value={notifyGroupId} onValueChange={setNotifyGroupId}>
                      <SelectTrigger className="h-8 w-40" data-testid="notify-group">
                        <SelectValue placeholder={t("ops.selectGroup")} />
                      </SelectTrigger>
                      <SelectContent>
                        {(groups.data?.data ?? []).map((g) => (
                          <SelectItem key={g.id} value={g.id}>
                            {g.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <Button
                      size="sm"
                      disabled={!notifyGroupId || action.isPending}
                      onClick={() => runAction("notify", { group_id: notifyGroupId })}
                      data-testid="action-notify"
                    >
                      {t("ops.notify")}
                    </Button>
                  </div>
                </div>
              )}

              <div>
                <h3 className="mb-2 text-sm font-semibold">
                  {t("ops.alerts")} ({detail.data.data.alerts.length})
                </h3>
                <AlertList alerts={detail.data.data.alerts} />
              </div>

              {/* LLM analysis (Feature A) */}
              <div data-testid="incident-analysis">
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">{t("llm.analysis")}</h3>
                  {canEdit && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        analyze.isPending ||
                        analysis.data?.data?.status === "pending" ||
                        analysis.data?.data?.status === "running"
                      }
                      onClick={() =>
                        analyze.mutate(
                          { force: analysis.data?.data?.status === "done" },
                          {
                            onError: (e) =>
                              toast({
                                variant: "destructive",
                                title: t("common.failed"),
                                description: e instanceof Error ? e.message : String(e),
                              }),
                          },
                        )
                      }
                      data-testid="analyze-button"
                    >
                      {analysis.data?.data?.status === "done"
                        ? t("llm.reanalyze")
                        : t("llm.analyze")}
                    </Button>
                  )}
                </div>
                {(() => {
                  const a = analysis.data?.data;
                  if (!a) return <p className="text-xs text-muted-foreground">{t("llm.none")}</p>;
                  if (a.status === "pending" || a.status === "running")
                    return (
                      <p className="text-xs text-muted-foreground" data-testid="analysis-running">
                        {t("llm.running")}
                      </p>
                    );
                  if (a.status === "failed")
                    return (
                      <p className="text-xs text-destructive" data-testid="analysis-failed">
                        {t("llm.failed")}: {a.error}
                      </p>
                    );
                  return (
                    <div className="space-y-1 rounded-lg border border-border/60 bg-muted/20 p-3 text-sm" data-testid="analysis-done">
                      {a.root_cause && (
                        <p>
                          <span className="font-semibold">{t("llm.rootCause")}:</span>{" "}
                          {a.root_cause}
                        </p>
                      )}
                      <p className="text-muted-foreground">{a.summary}</p>
                      <p className="text-[10px] text-muted-foreground">
                        {a.model} · {a.tokens_used} tokens
                      </p>
                    </div>
                  );
                })()}
              </div>

              <div>
                <h3 className="mb-2 text-sm font-semibold">{t("ops.timeline")}</h3>
                <Timeline events={detail.data.data.timeline} />
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
