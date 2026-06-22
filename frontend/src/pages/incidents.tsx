/** IMP Incidents page: browse incident CONTAINERS and the alerts inside each.
 *  Per-incident channel toggles (email/telegram/oncall), manual attach/detach,
 *  structured timeline. Auto-scoped by the l2 visibility choke point. */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useIncident, useIncidents } from "@/api/queries";
import { SeverityBadge } from "@/components/common/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import { hostnameFromLabels } from "@/lib/server-identity";
import { formatDate } from "@/lib/utils";
import type { IncidentStatus } from "@/types";

const statusVariant: Record<IncidentStatus, "critical" | "warning" | "success" | "secondary"> = {
  open: "critical",
  acknowledged: "warning",
  resolved: "success",
  suppressed: "secondary",
};

export function IncidentsPage() {
  const { t } = useTranslation();
  const [detailId, setDetailId] = useState<string | null>(null);
  // No status filter → the container list shows incidents in every state
  // (open/acknowledged/resolved/suppressed); the backend treats an absent
  // status as "all" (a sentinel like __all__ is not a valid IncidentStatus).
  const incidents = useIncidents({ limit: "50" });

  return (
    <div data-testid="incidents-page" className="space-y-4">
      <PageHeader title={t("nav.incidents")} description={t("incidents.description")} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("ops.incident")}</TableHead>
            <TableHead>{t("rules.severity")}</TableHead>
            <TableHead>{t("ops.status")}</TableHead>
            <TableHead>{t("incidents.origin")}</TableHead>
            <TableHead className="text-right">{t("ops.alerts")}</TableHead>
            <TableHead>{t("ops.lastSeen")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {(incidents.data?.data ?? []).map((inc) => (
            <TableRow
              key={inc.id}
              className="cursor-pointer"
              onClick={() => setDetailId(inc.id)}
              data-testid="incident-row"
            >
              <TableCell>
                <div className="font-medium">{inc.title}</div>
                <div className="text-xs text-muted-foreground">
                  {inc.cmdb_service_l2_code ?? "—"}
                </div>
              </TableCell>
              <TableCell>
                <SeverityBadge severity={inc.severity} />
              </TableCell>
              <TableCell>
                <Badge variant={statusVariant[inc.status]}>{inc.status}</Badge>
              </TableCell>
              <TableCell>
                <Badge variant="outline">{inc.origin}</Badge>
              </TableCell>
              <TableCell className="text-right">{inc.alert_count}</TableCell>
              <TableCell className="text-muted-foreground">{formatDate(inc.last_seen)}</TableCell>
            </TableRow>
          ))}
          {incidents.data?.data.length === 0 && (
            <TableRow>
              <TableCell colSpan={6} className="text-center text-muted-foreground">
                {t("incidents.none")}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <IncidentDetailDialog detailId={detailId} onClose={() => setDetailId(null)} />
    </div>
  );
}

function IncidentDetailDialog({
  detailId,
  onClose,
}: {
  detailId: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");
  const detail = useIncident(detailId);
  const inc = detail.data?.data;

  const fail = (e: unknown) =>
    toast({
      variant: "destructive",
      title: t("common.failed"),
      description: e instanceof Error ? e.message : String(e),
    });

  const patch = useApiMutation(
    (body: Record<string, boolean>) => api.patch(`/incidents/${detailId}`, body),
    ["incidents"],
  );
  const detach = useApiMutation(
    (alertId: string) => api.delete(`/incidents/${detailId}/alerts/${alertId}`),
    ["incidents"],
  );

  return (
    <Dialog open={!!detailId} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[88vh] max-w-4xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{inc?.title ?? t("ops.incident")}</DialogTitle>
        </DialogHeader>
        {!inc ? null : (
          <div className="space-y-4" data-testid="incident-detail">
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={inc.severity} />
              <Badge variant={statusVariant[inc.status]}>{inc.status}</Badge>
              <Badge variant="outline">{inc.origin}</Badge>
              {inc.cmdb_service_l2_code && (
                <Badge variant="secondary">{inc.cmdb_service_l2_code}</Badge>
              )}
            </div>

            {/* channel toggles */}
            <div className="flex flex-wrap gap-4 rounded-lg border border-border/60 bg-muted/30 p-3" data-testid="channel-toggles">
              {(["notify_email", "notify_telegram", "notify_oncall"] as const).map((ch) => (
                <label key={ch} className="flex items-center gap-2 text-sm">
                  <Switch
                    checked={inc[ch]}
                    disabled={!canEdit || patch.isPending}
                    onCheckedChange={(v) => patch.mutate({ [ch]: v }, { onError: fail })}
                    data-testid={`toggle-${ch}`}
                  />
                  {t(`incidents.${ch}`)}
                </label>
              ))}
            </div>

            {/* alerts inside */}
            <div>
              <h3 className="mb-2 text-sm font-semibold">
                {t("ops.alerts")} ({inc.alerts.length})
              </h3>
              <div className="space-y-1">
                {inc.alerts.map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-sm"
                    data-testid="incident-alert"
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={a.severity} />
                      <span className="font-medium">{a.name}</span>
                      <span className="text-xs text-muted-foreground">
                        {hostnameFromLabels(a.labels) ?? a.cmdb_hostname ?? a.cmdb_ci ?? "—"}
                      </span>
                    </span>
                    {canEdit && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => detach.mutate(a.id, { onError: fail })}
                        data-testid="detach"
                      >
                        {t("incidents.detach")}
                      </Button>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* timeline */}
            <div>
              <h3 className="mb-2 text-sm font-semibold">{t("ops.timeline")}</h3>
              <div className="space-y-1">
                {inc.timeline.map((e) => (
                  <div key={e.id} className="flex gap-2 text-xs">
                    <span className="w-32 shrink-0 text-muted-foreground">
                      {formatDate(e.created_at)}
                    </span>
                    <Badge variant="outline" className="h-5 shrink-0">
                      {e.kind}
                    </Badge>
                    <span className="min-w-0 flex-1 break-words text-muted-foreground">
                      {JSON.stringify(e.payload)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
