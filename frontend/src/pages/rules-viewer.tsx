/** Alert Rules viewer (route /alert-rules). Read-only table of the rules
 *  PULLED from the Mimir Ruler: what each rule is, how it's collected, its
 *  current value, base threshold, and any evaluation error.
 *
 *  HARD RULE: `expr` is shown as read-only monospace text (expandable). It is
 *  NEVER an input — atlas never accepts/exposes a PromQL editor. */

import { useMemo, useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useRulesPulled } from "@/api/queries";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { SeverityBadge } from "@/components/common/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn, formatDate, formatDuration } from "@/lib/utils";
import type { PulledRule } from "@/types";

const stateVariant: Record<string, "secondary" | "success" | "warning" | "critical"> = {
  firing: "critical",
  pending: "warning",
  inactive: "success",
  ok: "success",
};

export function RulesViewerPage() {
  const { t } = useTranslation();
  const pulled = useRulesPulled();
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const rules = useMemo(() => pulled.data?.data ?? [], [pulled.data]);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? rules.filter((r) => r.alertname.toLowerCase().includes(q)) : rules;
  }, [rules, search]);

  return (
    <div data-testid="rules-viewer-page" className="space-y-4">
      <PageHeader title={t("rulesViewer.title")} description={t("rulesViewer.description")} />

      <div className="relative w-72">
        <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          className="pl-8"
          placeholder={t("rulesViewer.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          data-testid="rules-search"
        />
      </div>

      <div className="rounded-lg border border-border/60">
        {pulled.isLoading ? (
          <div className="p-6">
            <LoadingSpinner />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" />
                <TableHead>{t("rulesViewer.alertname")}</TableHead>
                <TableHead>{t("rulesViewer.severity")}</TableHead>
                <TableHead>{t("rulesViewer.state")}</TableHead>
                <TableHead>{t("rulesViewer.health")}</TableHead>
                <TableHead className="text-right">{t("rulesViewer.value")}</TableHead>
                <TableHead className="text-right">{t("rulesViewer.baseThreshold")}</TableHead>
                <TableHead>{t("rulesViewer.for")}</TableHead>
                <TableHead>{t("rulesViewer.lastEval")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((r) => (
                <RuleRow
                  key={`${r.group_name}/${r.alertname}`}
                  rule={r}
                  expanded={expanded === `${r.group_name}/${r.alertname}`}
                  onToggle={() =>
                    setExpanded(
                      expanded === `${r.group_name}/${r.alertname}`
                        ? null
                        : `${r.group_name}/${r.alertname}`,
                    )
                  }
                />
              ))}
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={9} className="text-center text-sm text-muted-foreground">
                    {t("rulesViewer.none")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}

function RuleRow({
  rule,
  expanded,
  onToggle,
}: {
  rule: PulledRule;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  const healthBad = rule.health !== "" && rule.health !== "ok";

  return (
    <>
      <TableRow
        className={cn("cursor-pointer", healthBad && "bg-severity-critical/5")}
        onClick={onToggle}
        data-testid="rule-row"
      >
        <TableCell>
          {expanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </TableCell>
        <TableCell className="font-mono text-sm font-medium">{rule.alertname}</TableCell>
        <TableCell>
          {rule.severity ? <SeverityBadge severity={rule.severity} /> : "—"}
        </TableCell>
        <TableCell>
          {rule.state ? (
            <Badge variant={stateVariant[rule.state] ?? "secondary"}>{rule.state}</Badge>
          ) : (
            "—"
          )}
        </TableCell>
        <TableCell>
          {healthBad ? (
            <span
              className="flex items-center gap-1 text-severity-critical"
              data-testid="rule-health-bad"
            >
              <AlertTriangle className="h-3.5 w-3.5" />
              {rule.health || "err"}
            </span>
          ) : (
            <Badge variant="success">{rule.health || "ok"}</Badge>
          )}
        </TableCell>
        <TableCell className="text-right font-mono tabular-nums">
          {rule.value == null ? "—" : rule.value}
        </TableCell>
        <TableCell className="text-right font-mono tabular-nums">
          {rule.base_threshold == null
            ? "—"
            : `${rule.comparator ?? ""} ${rule.base_threshold}`.trim()}
        </TableCell>
        <TableCell className="text-sm text-muted-foreground">
          {formatDuration(rule.for_seconds)}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {formatDate(rule.last_evaluation)}
        </TableCell>
      </TableRow>
      {expanded && (
        <TableRow data-testid="rule-detail">
          <TableCell />
          <TableCell colSpan={8} className="space-y-2 py-3">
            {healthBad && rule.last_error && (
              <div
                className="rounded-md border border-severity-critical/30 bg-severity-critical/10 px-3 py-2 text-xs text-severity-critical"
                data-testid="rule-error"
              >
                <span className="font-semibold">{t("rulesViewer.lastError")}: </span>
                {rule.last_error}
              </div>
            )}
            <div>
              <p className="mb-1 text-xs font-semibold text-muted-foreground">
                {t("rulesViewer.expr")}
              </p>
              {/* expr is READ-ONLY display text — never an input (no PromQL UI) */}
              <pre
                className="overflow-x-auto rounded-md border border-border/60 bg-muted/40 p-2 text-xs font-mono"
                data-testid="rule-expr"
              >
                {rule.expr}
              </pre>
            </div>
            <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted-foreground">
              <span>
                {t("rulesViewer.namespace")}:{" "}
                <span className="font-mono text-foreground">{rule.namespace || "—"}</span>
              </span>
              <span>
                {t("rulesViewer.group")}:{" "}
                <span className="font-mono text-foreground">{rule.group_name || "—"}</span>
              </span>
              <span>
                {t("rulesViewer.synced")}:{" "}
                <span className="text-foreground">{formatDate(rule.synced_at)}</span>
              </span>
            </div>
            {Object.keys(rule.labels).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {Object.entries(rule.labels).map(([k, v]) => (
                  <Badge key={k} variant="outline" className="font-mono text-[10px]">
                    {k}={v}
                  </Badge>
                ))}
              </div>
            )}
          </TableCell>
        </TableRow>
      )}
    </>
  );
}
