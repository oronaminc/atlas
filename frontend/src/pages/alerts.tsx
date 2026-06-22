/** IMP Alerts page: browse/search EVERY stored alert (in an incident or not),
 *  full labels, filter by label dimensions, group-by counts, and promote an
 *  alert into a new incident (editor+). */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Flag } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useAlertGroups, useAlertsBrowse, useApiMutation } from "@/api/queries";
import { SeverityBadge } from "@/components/common/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import { hostnameFromLabels, instanceFromLabels } from "@/lib/server-identity";
import { formatDate } from "@/lib/utils";
import type { StoredAlert } from "@/types";

const GROUP_DIMS = ["cmdb_service_l2_code", "cmdb_service_l1_code", "client_address"] as const;

export function AlertsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const [zone, setZone] = useState("");
  const [hostname, setHostname] = useState("");
  const [severity, setSeverity] = useState("__all__");
  const [inIncident, setInIncident] = useState("__all__");
  const [groupBy, setGroupBy] = useState("__none__");
  const [expanded, setExpanded] = useState<string | null>(null);

  const params = useMemo<Record<string, string | undefined>>(
    () => ({
      cmdb_zone: zone || undefined,
      cmdb_hostname: hostname || undefined,
      severity: severity === "__all__" ? undefined : severity,
      in_incident: inIncident === "__all__" ? undefined : inIncident,
    }),
    [zone, hostname, severity, inIncident],
  );

  const grouped = groupBy !== "__none__";
  const list = useAlertsBrowse(grouped ? undefined : params);
  const groups = useAlertGroups(grouped ? { ...params, group_by: groupBy } : undefined);

  const promote = useApiMutation(
    (alertId: string) => api.post("/incidents", { alert_id: alertId }),
    ["alerts-browse", "incidents"],
  );

  const rows = list.data?.data ?? [];

  return (
    <div data-testid="alerts-page" className="space-y-4">
      <PageHeader title={t("nav.alerts")} description={t("alerts.description")} />

      <div className="flex flex-wrap items-end gap-2">
        <Input
          className="w-48"
          placeholder={t("alerts.hostname")}
          value={hostname}
          onChange={(e) => setHostname(e.target.value)}
          data-testid="filter-hostname"
        />
        <Input
          className="w-40"
          placeholder={t("alerts.zone")}
          value={zone}
          onChange={(e) => setZone(e.target.value)}
          data-testid="filter-zone"
        />
        <Select value={severity} onValueChange={setSeverity}>
          <SelectTrigger className="w-36" data-testid="filter-severity">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">{t("alerts.allSeverities")}</SelectItem>
            <SelectItem value="critical">critical</SelectItem>
            <SelectItem value="warning">warning</SelectItem>
            <SelectItem value="info">info</SelectItem>
          </SelectContent>
        </Select>
        <Select value={inIncident} onValueChange={setInIncident}>
          <SelectTrigger className="w-40" data-testid="filter-in-incident">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">{t("alerts.anyIncident")}</SelectItem>
            <SelectItem value="true">{t("alerts.inIncident")}</SelectItem>
            <SelectItem value="false">{t("alerts.free")}</SelectItem>
          </SelectContent>
        </Select>
        <Select value={groupBy} onValueChange={setGroupBy}>
          <SelectTrigger className="w-52" data-testid="group-by">
            <SelectValue placeholder={t("alerts.groupBy")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">{t("alerts.noGrouping")}</SelectItem>
            {GROUP_DIMS.map((d) => (
              <SelectItem key={d} value={d}>
                {d}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {grouped ? (
        <div className="rounded-lg border border-border/60" data-testid="alert-groups">
          {(groups.data?.data ?? []).map((g) => (
            <div
              key={g.value}
              className="flex items-center justify-between border-b border-border/40 px-3 py-2 text-sm last:border-0"
            >
              <span className="font-mono">{g.value}</span>
              <Badge variant="secondary">{g.count}</Badge>
            </div>
          ))}
          {groups.data?.data.length === 0 && (
            <div className="px-3 py-2 text-sm text-muted-foreground">{t("alerts.none")}</div>
          )}
        </div>
      ) : (
        <div className="space-y-1" data-testid="alert-list">
          {rows.map((a) => (
            <AlertRow
              key={a.id}
              alert={a}
              expanded={expanded === a.id}
              onToggle={() => setExpanded(expanded === a.id ? null : a.id)}
              canEdit={canEdit}
              onPromote={() =>
                promote.mutate(a.id, {
                  onSuccess: () => toast({ title: t("alerts.promoted") }),
                  onError: (e) =>
                    toast({
                      variant: "destructive",
                      title: t("common.failed"),
                      description: e instanceof Error ? e.message : String(e),
                    }),
                })
              }
            />
          ))}
          {rows.length === 0 && (
            <div className="px-3 py-6 text-center text-sm text-muted-foreground">
              {t("alerts.none")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AlertRow({
  alert,
  expanded,
  onToggle,
  canEdit,
  onPromote,
}: {
  alert: StoredAlert;
  expanded: boolean;
  onToggle: () => void;
  canEdit: boolean;
  onPromote: () => void;
}) {
  const { t } = useTranslation();
  const host = hostnameFromLabels(alert.labels) ?? alert.cmdb_hostname ?? alert.cmdb_ci ?? "—";
  const instance = instanceFromLabels(alert.labels);
  return (
    <div
      className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-sm"
      data-testid="alert-row"
    >
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={onToggle}
          className="flex min-w-0 items-start gap-2 text-left"
        >
          {expanded ? (
            <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={alert.severity} />
              <span className="font-medium">{alert.name}</span>
              {alert.incident_id ? (
                <Badge variant="outline">{t("alerts.inIncident")}</Badge>
              ) : (
                <Badge variant="secondary">{t("alerts.free")}</Badge>
              )}
              {alert.suppressed && <Badge variant="outline">{t("alerts.suppressed")}</Badge>}
            </span>
            <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{host}</span>
              {instance && <span className="font-mono">{instance}</span>}
              {alert.cmdb_service_l2_code && <span>· {alert.cmdb_service_l2_code}</span>}
              <span>· {formatDate(alert.received_at)}</span>
            </span>
          </span>
        </button>
        {canEdit && !alert.incident_id && (
          <Button size="sm" variant="outline" onClick={onPromote} data-testid="promote">
            <Flag className="h-3 w-3" />
            {t("alerts.promote")}
          </Button>
        )}
      </div>
      {expanded && (
        <dl className="mt-2 grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-1 border-t border-border/40 pt-2 text-xs">
          {Object.entries(alert.labels).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="truncate font-mono text-muted-foreground">{k}</dt>
              <dd className="break-all font-mono">{v}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
