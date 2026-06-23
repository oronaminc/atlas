/** Alerts page: browse/search EVERY stored alert (in an incident or not),
 *  full labels, label-autocomplete filters, a date-range window, group-by
 *  counts, cursor pagination, and promote-to-incident (editor+). */

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Flag } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  useAlertGroups,
  useAlertsBrowse,
  useApiMutation,
  useLabelValues,
} from "@/api/queries";
import { SeverityBadge } from "@/components/common/status-badge";
import { DateRangePicker, resolvePreset, type DateRange } from "@/components/common/date-range-picker";
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
import { formatDate } from "@/lib/utils";
import type { StoredAlert } from "@/types";

const GROUP_DIMS = ["cmdb_service_l2_code", "cmdb_service_l1_code", "client_address"] as const;
const PAGE_SIZE = 50;

export function AlertsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const [zone, setZone] = useState("");
  const [hostname, setHostname] = useState("");
  const [cmdbCi, setCmdbCi] = useState("");
  const [severity, setSeverity] = useState("__all__");
  const [inIncident, setInIncident] = useState("__all__");
  const [groupBy, setGroupBy] = useState("__none__");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [range, setRange] = useState<DateRange>(() => resolvePreset(24, "24h"));

  // cursor pagination: a stack of cursors (one per visited page)
  const [cursors, setCursors] = useState<(string | undefined)[]>([undefined]);

  const hostnameValues = useLabelValues("cmdb_hostname");
  const zoneValues = useLabelValues("cmdb_zone");
  const cmdbCiValues = useLabelValues("cmdb_ci");

  const baseParams = useMemo<Record<string, string | undefined>>(
    () => ({
      cmdb_zone: zone || undefined,
      cmdb_hostname: hostname || undefined,
      cmdb_ci: cmdbCi || undefined,
      severity: severity === "__all__" ? undefined : severity,
      in_incident: inIncident === "__all__" ? undefined : inIncident,
      start: range.start,
      end: range.end,
    }),
    [zone, hostname, cmdbCi, severity, inIncident, range],
  );

  // reset to first page whenever the filter set changes
  useEffect(() => setCursors([undefined]), [baseParams, groupBy]);

  const grouped = groupBy !== "__none__";
  const pageIndex = cursors.length - 1;
  const currentCursor = cursors[pageIndex];

  const listParams = useMemo(
    () => ({ ...baseParams, limit: String(PAGE_SIZE), cursor: currentCursor }),
    [baseParams, currentCursor],
  );
  const list = useAlertsBrowse(grouped ? undefined : listParams);
  const groups = useAlertGroups(grouped ? { ...baseParams, group_by: groupBy } : undefined);

  const promote = useApiMutation(
    (alertId: string) => api.post("/incidents", { alert_id: alertId }),
    ["alerts-browse", "incidents"],
  );

  const rows = list.data?.data ?? [];
  const nextCursor = list.data?.meta?.next_cursor ?? null;

  return (
    <div data-testid="alerts-page" className="space-y-4">
      <PageHeader
        title={t("nav.alerts")}
        description={t("alerts.description")}
        actions={<DateRangePicker value={range} onChange={setRange} />}
      />

      <div className="flex flex-wrap items-end gap-2">
        <Input
          className="w-48"
          placeholder={t("alerts.hostname")}
          list="alerts-hostname-values"
          value={hostname}
          onChange={(e) => setHostname(e.target.value)}
          data-testid="filter-hostname"
        />
        <datalist id="alerts-hostname-values">
          {(hostnameValues.data?.data ?? []).map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
        <Input
          className="w-40"
          placeholder={t("alerts.zone")}
          list="alerts-zone-values"
          value={zone}
          onChange={(e) => setZone(e.target.value)}
          data-testid="filter-zone"
        />
        <datalist id="alerts-zone-values">
          {(zoneValues.data?.data ?? []).map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
        <Input
          className="w-44"
          placeholder={t("alerts.cmdbCi")}
          list="alerts-cmdbci-values"
          value={cmdbCi}
          onChange={(e) => setCmdbCi(e.target.value)}
          data-testid="filter-cmdb-ci"
        />
        <datalist id="alerts-cmdbci-values">
          {(cmdbCiValues.data?.data ?? []).map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
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
        <>
          <div className="rounded-lg border border-border/60" data-testid="alert-list">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-8" />
                  <TableHead>{t("alerts.colSeverity")}</TableHead>
                  <TableHead>{t("alerts.colName")}</TableHead>
                  <TableHead>{t("alerts.colHostname")}</TableHead>
                  <TableHead>{t("alerts.colZone")}</TableHead>
                  <TableHead>{t("alerts.colService")}</TableHead>
                  <TableHead>{t("alerts.colStatus")}</TableHead>
                  <TableHead>{t("alerts.colIncident")}</TableHead>
                  <TableHead>{t("alerts.colReceived")}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
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
                  <TableRow>
                    <TableCell colSpan={10} className="text-center text-sm text-muted-foreground">
                      {t("alerts.none")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>

          {/* cursor pagination */}
          <div className="flex items-center justify-between">
            <Button
              variant="outline"
              size="sm"
              disabled={pageIndex === 0}
              onClick={() => setCursors((c) => c.slice(0, -1))}
              data-testid="alerts-prev"
            >
              {t("common.previous")}
            </Button>
            <span className="text-xs text-muted-foreground">
              {t("alerts.page", { n: pageIndex + 1 })}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={!nextCursor}
              onClick={() => nextCursor && setCursors((c) => [...c, nextCursor])}
              data-testid="alerts-next"
            >
              {t("common.next")}
            </Button>
          </div>
        </>
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
  const host = alert.cmdb_hostname ?? alert.cmdb_ci ?? "—";
  return (
    <>
      <TableRow className="cursor-pointer" onClick={onToggle} data-testid="alert-row">
        <TableCell>
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </TableCell>
        <TableCell>
          <SeverityBadge severity={alert.severity} />
        </TableCell>
        <TableCell className="font-medium">{alert.name}</TableCell>
        <TableCell className="font-mono text-xs">{host}</TableCell>
        <TableCell className="text-xs text-muted-foreground">{alert.cmdb_zone ?? "—"}</TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {alert.cmdb_service_l2_code ?? "—"}
        </TableCell>
        <TableCell>
          {alert.suppressed ? (
            <Badge variant="outline">{t("alerts.suppressed")}</Badge>
          ) : (
            <span className="text-xs text-muted-foreground">{alert.status}</span>
          )}
        </TableCell>
        <TableCell>
          {alert.incident_id ? (
            <Badge variant="outline">{t("alerts.inIncident")}</Badge>
          ) : (
            <Badge variant="secondary">{t("alerts.free")}</Badge>
          )}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {formatDate(alert.received_at)}
        </TableCell>
        <TableCell onClick={(e) => e.stopPropagation()}>
          {canEdit && !alert.incident_id && (
            <Button size="sm" variant="outline" onClick={onPromote} data-testid="promote">
              <Flag className="h-3 w-3" />
              {t("alerts.promote")}
            </Button>
          )}
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow>
          <TableCell />
          <TableCell colSpan={9}>
            <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-1 text-xs">
              {Object.entries(alert.labels).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="truncate font-mono text-muted-foreground">{k}</dt>
                  <dd className="break-all font-mono">{v}</dd>
                </div>
              ))}
            </dl>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
