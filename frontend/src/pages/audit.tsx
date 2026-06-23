import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuditLogs } from "@/api/queries";
import { DataTable, type Column } from "@/components/common/data-table";
import { Pager } from "@/components/common/pager";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
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
import { formatDate } from "@/lib/utils";
import type { AuditLog } from "@/types";

const ALL = "__all__";

export function AuditPage() {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [resourceFilter, setResourceFilter] = useState(ALL);
  const [emergencyOnly, setEmergencyOnly] = useState(ALL);
  const [detail, setDetail] = useState<AuditLog | null>(null);

  const logs = useAuditLogs({
    page: String(page),
    page_size: "25",
    resource_type: resourceFilter === ALL ? undefined : resourceFilter,
    emergency: emergencyOnly === ALL ? undefined : emergencyOnly,
  });

  const meta = logs.data?.meta;

  const columns: Column<AuditLog>[] = [
    {
      key: "action",
      header: "Action",
      render: (l) => <span className="font-medium">{l.action}</span>,
    },
    {
      key: "resource",
      header: "Resource",
      render: (l) => (
        <div>
          <Badge variant="outline">{l.resource_type}</Badge>
          <span className="ml-2 font-mono text-xs text-muted-foreground">
            {l.resource_id?.slice(0, 8)}
          </span>
        </div>
      ),
    },
    {
      key: "emergency",
      header: "Emergency",
      render: (l) =>
        l.emergency ? <Badge variant="destructive">emergency</Badge> : null,
    },
    {
      key: "ip",
      header: "IP",
      render: (l) => <span className="text-muted-foreground">{l.ip ?? "-"}</span>,
    },
    {
      key: "time",
      header: "Time",
      render: (l) => <span className="text-muted-foreground">{formatDate(l.created_at)}</span>,
    },
  ];

  return (
    <div>
      <PageHeader title={t("nav.audit")} />
      <DataTable
        columns={columns}
        rows={logs.data?.data ?? []}
        rowKey={(l) => l.id}
        loading={logs.isLoading}
        filters={
          <div className="flex gap-2">
            <Select
              value={resourceFilter}
              onValueChange={(v) => {
                setResourceFilter(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>resource: all</SelectItem>
                <SelectItem value="alert_rule">alert_rule</SelectItem>
                <SelectItem value="rule_group">rule_group</SelectItem>
                <SelectItem value="server">server</SelectItem>
                <SelectItem value="user">user</SelectItem>
                <SelectItem value="group">group</SelectItem>
                <SelectItem value="receiver">receiver</SelectItem>
                <SelectItem value="silence">silence</SelectItem>
              </SelectContent>
            </Select>
            <Select
              value={emergencyOnly}
              onValueChange={(v) => {
                setEmergencyOnly(v);
                setPage(1);
              }}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>emergency: all</SelectItem>
                <SelectItem value="true">emergency only</SelectItem>
              </SelectContent>
            </Select>
          </div>
        }
        onRowClick={(l) => setDetail(l)}
      />

      <div className="mt-4">
        <Pager
          page={meta?.page ?? page}
          pages={meta?.pages ?? 1}
          total={meta?.total}
          onPage={setPage}
        />
      </div>

      <Dialog open={!!detail} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {detail?.action} — {detail?.resource_type}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <h3 className="mb-1 text-sm font-medium">Before</h3>
              <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(detail?.before ?? null, null, 2)}
              </pre>
            </div>
            <div>
              <h3 className="mb-1 text-sm font-medium">After</h3>
              <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">
                {JSON.stringify(detail?.after ?? null, null, 2)}
              </pre>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
