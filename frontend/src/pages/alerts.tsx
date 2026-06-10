import { useTranslation } from "react-i18next";

import { useActiveAlerts } from "@/api/queries";
import { DataTable, type Column } from "@/components/common/data-table";
import { EmptyState } from "@/components/common/empty-state";
import { SeverityBadge } from "@/components/common/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import type { ActiveAlert } from "@/types";

export function AlertsPage() {
  const { t } = useTranslation();
  const alerts = useActiveAlerts();

  const columns: Column<ActiveAlert>[] = [
    {
      key: "name",
      header: "Alert",
      render: (a) => (
        <span className="font-medium">{a.labels.alertname ?? "(unnamed)"}</span>
      ),
    },
    {
      key: "severity",
      header: t("rules.severity"),
      render: (a) => <SeverityBadge severity={a.labels.severity ?? "info"} />,
    },
    {
      key: "state",
      header: "State",
      render: (a) => <Badge variant="outline">{a.status.state}</Badge>,
    },
    {
      key: "summary",
      header: "Summary",
      render: (a) => (
        <span className="text-muted-foreground">
          {a.annotations.summary ?? a.annotations.description ?? "-"}
        </span>
      ),
    },
    {
      key: "since",
      header: "Since",
      render: (a) => formatDate(a.startsAt),
    },
  ];

  if (alerts.isError) {
    return (
      <div>
        <PageHeader title={t("nav.alerts")} />
        <EmptyState
          title="Alertmanager 연결 실패"
          description="Alertmanager에 연결할 수 없습니다. 백엔드 설정(MIMIR_ALERTMANAGER_URL)을 확인하세요."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title={t("nav.alerts")} />
      <DataTable
        columns={columns}
        rows={alerts.data?.data ?? []}
        rowKey={(a) => a.fingerprint}
        loading={alerts.isLoading}
      />
    </div>
  );
}
