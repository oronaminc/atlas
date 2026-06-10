import { Activity, AlertTriangle, BellOff, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useActiveAlerts, useAuditLogs, useSyncState } from "@/api/queries";
import { PageHeader } from "@/components/layout/page-header";
import { StatusBadge } from "@/components/common/status-badge";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDate } from "@/lib/utils";

function SummaryCard({
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

export function DashboardPage() {
  const { t } = useTranslation();
  const alerts = useActiveAlerts();
  const sync = useSyncState();
  const audit = useAuditLogs({ limit: "8" });

  const alertList = alerts.data?.data ?? [];
  const critical = alertList.filter((a) => a.labels.severity === "critical").length;
  const silenced = alertList.filter((a) => a.status.state === "suppressed").length;

  return (
    <div>
      <PageHeader title={t("nav.dashboard")} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          title={t("dashboard.activeAlerts")}
          value={alerts.isError ? "-" : alertList.length}
          icon={Activity}
        />
        <SummaryCard
          title="Critical"
          value={alerts.isError ? "-" : critical}
          icon={AlertTriangle}
          tone="text-destructive"
        />
        <SummaryCard title="Silenced" value={alerts.isError ? "-" : silenced} icon={BellOff} />
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">{t("dashboard.syncState")}</CardTitle>
            <ShieldAlert className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {sync.data?.data.length ? (
              sync.data.data.map((s) => (
                <div key={s.id} className="flex items-center gap-1 text-sm">
                  <span className="text-muted-foreground">{s.target}</span>
                  <StatusBadge status={s.status} />
                </div>
              ))
            ) : (
              <Badge variant="secondary">no data</Badge>
            )}
          </CardContent>
        </Card>
      </div>

      {alerts.isError && (
        <p className="mt-4 text-sm text-muted-foreground">
          Alertmanager에 연결할 수 없습니다 — 알림 요약을 표시할 수 없습니다.
        </p>
      )}

      <Card className="mt-6">
        <CardHeader>
          <CardTitle className="text-base">{t("dashboard.recentAudit")}</CardTitle>
        </CardHeader>
        <CardContent>
          {audit.isLoading ? (
            <LoadingSpinner />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Action</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>Emergency</TableHead>
                  <TableHead>Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(audit.data?.data ?? []).map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="font-medium">{log.action}</TableCell>
                    <TableCell>{log.resource_type}</TableCell>
                    <TableCell>
                      {log.emergency && <Badge variant="destructive">emergency</Badge>}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDate(log.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
