/** Incident-dialog building blocks: an alert row that identifies the SERVER
 *  (hostname + ip:port, cmdb_ci secondary) and shows all labels/annotations as
 *  a readable grid, and a timeline that renders each event by KIND instead of
 *  dumping raw JSON. */

import { useState } from "react";
import type { TFunction } from "i18next";
import { ChevronDown, ChevronRight, Server } from "lucide-react";
import { useTranslation } from "react-i18next";

import { SeverityBadge } from "@/components/common/status-badge";
import { Badge } from "@/components/ui/badge";
import { formatDate } from "@/lib/utils";
import {
  cmdbCiFromLabels,
  hostnameFromLabels,
  instanceFromLabels,
} from "@/lib/server-identity";
import type { IncidentDetail } from "@/types";

type Alert = IncidentDetail["alerts"][number];
type TimelineEvent = IncidentDetail["timeline"][number];

function KeyValueGrid({ data }: { data: Record<string, string> }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[minmax(7rem,auto)_1fr] gap-x-3 gap-y-1 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="truncate font-mono text-muted-foreground" title={k}>
            {k}
          </dt>
          <dd className="break-all font-mono">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function AlertRow({ alert }: { alert: Alert }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const host = hostnameFromLabels(alert.labels);
  const instance = instanceFromLabels(alert.labels);
  const cmdb = cmdbCiFromLabels(alert.labels);
  const labelCount = Object.keys(alert.labels ?? {}).length;
  const annCount = Object.keys(alert.annotations ?? {}).length;

  return (
    <div
      className="rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-sm"
      data-testid="alert-row"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium">{alert.name}</span>
            <span className="text-xs text-muted-foreground">
              {alert.source} · ×{alert.dedup_count}
            </span>
          </div>
          {/* SERVER identity: hostname primary, ip:port next, cmdb_ci secondary */}
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            <span className="inline-flex items-center gap-1 font-medium" data-testid="alert-host">
              <Server className="h-3 w-3 text-muted-foreground" />
              {host ?? t("ops.unknownHost")}
            </span>
            {instance && <span className="font-mono text-muted-foreground">{instance}</span>}
            {cmdb && (
              <span className="font-mono text-[10px] text-muted-foreground/70">{cmdb}</span>
            )}
          </div>
        </div>
        <SeverityBadge severity={alert.severity} />
      </div>

      {(labelCount > 0 || annCount > 0) && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-1 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          data-testid="alert-labels-toggle"
        >
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {t("ops.labelsCount", { count: labelCount })}
        </button>
      )}
      {open && (
        <div className="mt-2 space-y-2 border-t border-border/40 pt-2" data-testid="alert-labels">
          <KeyValueGrid data={alert.labels ?? {}} />
          {annCount > 0 && (
            <div className="space-y-1">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("rules.annotations")}
              </div>
              <KeyValueGrid data={alert.annotations ?? {}} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function AlertList({ alerts }: { alerts: Alert[] }) {
  return (
    <div className="space-y-1" data-testid="alert-list">
      {alerts.map((a) => (
        <AlertRow key={a.id} alert={a} />
      ))}
    </div>
  );
}

function p(payload: Record<string, unknown>, key: string): string | undefined {
  const v = payload[key];
  return v == null ? undefined : String(v);
}

/** Human-readable summary of a timeline event, by kind. */
function describe(event: TimelineEvent, t: TFunction): React.ReactNode {
  const pl = event.payload ?? {};
  switch (event.kind) {
    case "created":
      return <span className="text-muted-foreground">{t("ops.tlCreated")}</span>;
    case "alert_attached":
      return (
        <span>
          <span className="font-medium">{p(pl, "name") ?? "alert"}</span>
          <span className="text-muted-foreground"> {t("ops.tlAttached")}</span>
        </span>
      );
    case "status_changed":
      return (
        <span>
          <span className="font-mono">{p(pl, "from") ?? "?"}</span>
          <span className="text-muted-foreground"> → </span>
          <span className="font-mono">{p(pl, "to") ?? "?"}</span>
          {p(pl, "actor") && (
            <span className="text-muted-foreground"> · {p(pl, "actor")}</span>
          )}
          {p(pl, "note") && <div className="text-muted-foreground">{p(pl, "note")}</div>}
        </span>
      );
    case "comment":
      return (
        <span>
          {p(pl, "author") && <span className="font-medium">{p(pl, "author")}: </span>}
          <span className="whitespace-pre-wrap">{p(pl, "text")}</span>
        </span>
      );
    case "notification_muted": {
      const pairs = (pl.muted_pairs as { cmdb_ci?: string; alertname?: string }[]) ?? [];
      return (
        <span className="text-muted-foreground">
          {t("ops.tlMuted")}
          {p(pl, "reason") ? ` (${p(pl, "reason")})` : ""}
          {pairs.length > 0 && (
            <span className="ml-1 font-mono">
              {pairs.map((x) => `${x.alertname ?? "*"}@${x.cmdb_ci ?? "*"}`).join(", ")}
            </span>
          )}
        </span>
      );
    }
    case "llm_analysis":
      return (
        <span>
          <span className="font-medium">{t("llm.rootCause")}: </span>
          <span className="whitespace-pre-wrap">{p(pl, "root_cause") ?? p(pl, "summary")}</span>
        </span>
      );
    default:
      return <span className="whitespace-pre-wrap break-all text-muted-foreground">
        {JSON.stringify(pl)}
      </span>;
  }
}

function TimelineItem({ event }: { event: TimelineEvent }) {
  const { t } = useTranslation();
  const [raw, setRaw] = useState(false);
  const hasPayload = Object.keys(event.payload ?? {}).length > 0;
  return (
    <div className="flex gap-2 text-xs" data-testid="timeline-item">
      <span className="w-32 shrink-0 text-muted-foreground">{formatDate(event.created_at)}</span>
      <Badge variant="outline" className="h-5 shrink-0">
        {event.kind}
      </Badge>
      <div className="min-w-0 flex-1">
        {describe(event, t)}
        {hasPayload && (
          <button
            type="button"
            onClick={() => setRaw((r) => !r)}
            className="ml-2 text-[10px] text-muted-foreground/60 hover:text-foreground"
            data-testid="timeline-raw-toggle"
          >
            {raw ? t("ops.hideRaw") : t("ops.viewRaw")}
          </button>
        )}
        {raw && (
          <pre className="mt-1 overflow-x-auto rounded bg-muted/40 p-2 text-[10px] leading-relaxed">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="space-y-1.5" data-testid="timeline">
      {events.map((e) => (
        <TimelineItem key={e.id} event={e} />
      ))}
    </div>
  );
}
