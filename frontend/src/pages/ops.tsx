import { useState } from "react";
import { Activity, BellRing, Flame, Server } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  useApiMutation,
  useGroups,
  useIncident,
  useIncidents,
  useNotificationRows,
  useStatsHosts,
  useStatsOverview,
  useStatsTrend,
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TrendChart } from "@/features/ops/trend-chart";
import { formatDate } from "@/lib/utils";
import type { IncidentStatus } from "@/types";

const ALL = "__all__";
// "active" = needs attention: excludes resolved AND suppressed
const ACTIVE = "open,acknowledged";

const incidentStatusVariant: Record<
  IncidentStatus,
  "destructive" | "warning" | "success" | "secondary"
> = {
  open: "destructive",
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
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <Icon className={`h-4 w-4 ${tone ?? "text-muted-foreground"}`} />
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
      </CardContent>
    </Card>
  );
}

export function OpsPage() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");
  const [statusFilter, setStatusFilter] = useState(ACTIVE);
  const [trendHours, setTrendHours] = useState(24);
  const [detailId, setDetailId] = useState<string | null>(null);

  const overview = useStatsOverview();
  const incidents = useIncidents({
    limit: "20",
    status: statusFilter === ALL ? undefined : statusFilter,
  });
  const notifications = useNotificationRows({ limit: "20" });
  const trend = useStatsTrend(trendHours);
  const hostStats = useStatsHosts();
  const detail = useIncident(detailId);

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
          tone="text-amber-500"
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        {/* Panel 1: incidents */}
        <Card data-testid="panel-incidents">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base">{t("ops.incidents")}</CardTitle>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-8 w-40">
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
                        <div className="text-xs text-muted-foreground">
                          {incident.group_key ?? "-"}
                        </div>
                      </TableCell>
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
            <div className="flex gap-1">
              {[24, 168].map((h) => (
                <Button
                  key={h}
                  size="sm"
                  variant={trendHours === h ? "default" : "outline"}
                  onClick={() => setTrendHours(h)}
                >
                  {h === 24 ? "24h" : "7d"}
                </Button>
              ))}
            </div>
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
        <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
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
                  className="flex flex-wrap items-center gap-2 rounded-md border p-2"
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
                <div className="space-y-1">
                  {detail.data.data.alerts.map((alert) => (
                    <div
                      key={alert.id}
                      className="flex items-center justify-between rounded-md border px-3 py-2 text-sm"
                    >
                      <div>
                        <span className="font-medium">{alert.name}</span>
                        <span className="ml-2 text-xs text-muted-foreground">
                          {alert.source} · ×{alert.dedup_count}
                        </span>
                      </div>
                      <SeverityBadge severity={alert.severity} />
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <h3 className="mb-2 text-sm font-semibold">{t("ops.timeline")}</h3>
                <div className="space-y-1">
                  {detail.data.data.timeline.map((event) => (
                    <div key={event.id} className="flex min-w-0 gap-2 text-xs">
                      <span className="w-36 shrink-0 text-muted-foreground">
                        {formatDate(event.created_at)}
                      </span>
                      <Badge variant="outline">{event.kind}</Badge>
                      <span className="min-w-0 flex-1 truncate text-muted-foreground">
                        {JSON.stringify(event.payload)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
