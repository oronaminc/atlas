/** Threshold overrides. Two cards:
 *  1. Rule catalog metadata — per-alertname comparator (>/<), unit, and the
 *     Mimir value_query (with a {{cmdb_ci}} slot). No value_query = pass-through
 *     (the ingest filter never suppresses, fail-open).
 *  2. Threshold overrides — the alertname is picked from the rules PULLED from
 *     the Mimir Ruler (read-only), and the target is EITHER a specific server
 *     (cmdb_ci) OR a label match (key=value). The correlation worker fetches the
 *     live value from Mimir at filter time and suppresses below-threshold alerts. */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useRulesPulled } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layout/page-header";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import { SeverityBadge } from "@/components/common/status-badge";

interface CatalogRule {
  alertname: string;
  comparator: ">" | "<" | null;
  unit: string | null;
  value_query: string | null;
}
interface ThresholdOverrideOut {
  id: string;
  alertname: string;
  target_cmdb_ci: string | null;
  target_label_key: string | null;
  target_label_value: string | null;
  value: number;
}

type TargetKind = "cmdb_ci" | "label";

export function ThresholdsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const pulled = useRulesPulled();
  const catalog = useQuery({
    queryKey: ["rule-catalog"],
    queryFn: () => api.get<CatalogRule[]>("/rule-catalog"),
  });
  const overrides = useQuery({
    queryKey: ["threshold-overrides"],
    queryFn: () => api.get<ThresholdOverrideOut[]>("/threshold-overrides"),
  });

  const fail = (e: unknown) =>
    toast({
      variant: "destructive",
      title: t("common.failed"),
      description: e instanceof Error ? e.message : String(e),
    });

  // --- catalog metadata editor ---
  const [ruleSearch, setRuleSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [comparator, setComparator] = useState<">" | "<">(">");
  const [unit, setUnit] = useState("");
  const [valueQuery, setValueQuery] = useState("");

  const rules = useMemo(() => catalog.data?.data ?? [], [catalog.data]);
  const filteredRules = useMemo(() => {
    const q = ruleSearch.trim().toLowerCase();
    return q ? rules.filter((r) => r.alertname.toLowerCase().includes(q)) : rules;
  }, [rules, ruleSearch]);

  const selectRule = (r: CatalogRule) => {
    setSelected(r.alertname);
    setComparator(r.comparator ?? ">");
    setUnit(r.unit ?? "");
    setValueQuery(r.value_query ?? "");
  };

  const saveCatalog = useApiMutation(
    () =>
      api.patch(`/rule-catalog/${encodeURIComponent(selected as string)}`, {
        comparator,
        unit: unit || null,
        value_query: valueQuery || null,
      }),
    ["rule-catalog"],
  );

  // --- override create (pick alertname from the pulled Ruler rules) ---
  const pulledRules = useMemo(() => pulled.data?.data ?? [], [pulled.data]);
  const [ovrSearch, setOvrSearch] = useState("");
  const [ovrAlert, setOvrAlert] = useState<string | null>(null);
  const [targetKind, setTargetKind] = useState<TargetKind>("cmdb_ci");
  const [cmdb, setCmdb] = useState("");
  const [labelKey, setLabelKey] = useState("");
  const [labelValue, setLabelValue] = useState("");
  const [ovrValue, setOvrValue] = useState("");

  const filteredPulled = useMemo(() => {
    const q = ovrSearch.trim().toLowerCase();
    return q
      ? pulledRules.filter((r) => r.alertname.toLowerCase().includes(q))
      : pulledRules;
  }, [pulledRules, ovrSearch]);

  const createOverride = useApiMutation(
    () =>
      api.post("/threshold-overrides", {
        alertname: ovrAlert,
        ...(targetKind === "cmdb_ci"
          ? { target_cmdb_ci: cmdb }
          : { target_label_key: labelKey, target_label_value: labelValue }),
        value: Number(ovrValue),
      }),
    ["threshold-overrides"],
    () => {
      setCmdb("");
      setLabelKey("");
      setLabelValue("");
      setOvrValue("");
    },
  );
  const deleteOverride = useApiMutation(
    (id: string) => api.delete(`/threshold-overrides/${id}`),
    ["threshold-overrides"],
  );

  const catalogMeta = (name: string) => rules.find((r) => r.alertname === name);
  const selectedRuleMeta = ovrAlert ? catalogMeta(ovrAlert) : undefined;
  const canSubmitOverride =
    !!ovrAlert &&
    ovrValue.trim() !== "" &&
    !Number.isNaN(Number(ovrValue)) &&
    (targetKind === "cmdb_ci"
      ? !!cmdb.trim()
      : !!labelKey.trim() && !!labelValue.trim());

  return (
    <div data-testid="thresholds-page" className="space-y-6">
      <PageHeader title={t("thresholds.title")} description={t("thresholds.description")} />

      {/* Rule catalog metadata */}
      <Card data-testid="catalog-card">
        <CardHeader>
          <CardTitle className="text-base">{t("thresholds.catalog")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          {/* rule picker */}
          <div className="space-y-2">
            <div className="relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder={t("thresholds.searchRules")}
                value={ruleSearch}
                onChange={(e) => setRuleSearch(e.target.value)}
                data-testid="catalog-search"
              />
            </div>
            <div className="max-h-64 overflow-y-auto rounded-md border border-border/60" data-testid="catalog-list">
              {filteredRules.map((r) => (
                <button
                  key={r.alertname}
                  type="button"
                  onClick={() => selectRule(r)}
                  data-testid="catalog-rule"
                  className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-accent ${
                    selected === r.alertname ? "bg-accent text-accent-foreground" : ""
                  }`}
                >
                  <span className="font-mono">{r.alertname}</span>
                  {r.value_query ? (
                    <Badge variant="secondary" data-testid="catalog-configured">
                      {r.comparator} {r.unit}
                    </Badge>
                  ) : (
                    <Badge variant="outline" data-testid="catalog-passthrough">
                      {t("thresholds.passthrough")}
                    </Badge>
                  )}
                </button>
              ))}
              {filteredRules.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground" data-testid="catalog-empty">
                  {t("thresholds.noRules")}
                </div>
              )}
            </div>
          </div>

          {/* metadata form */}
          {selected ? (
            <div className="space-y-3" data-testid="catalog-form">
              <div className="text-sm font-medium font-mono">{selected}</div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-muted-foreground w-24">
                  {t("thresholds.comparator")}
                </label>
                <Select
                  value={comparator}
                  onValueChange={(v) => setComparator(v as ">" | "<")}
                  disabled={!canEdit}
                >
                  <SelectTrigger className="w-40" data-testid="catalog-comparator">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value=">" data-testid="cmp-gt">
                      {t("thresholds.cmpGt")}
                    </SelectItem>
                    <SelectItem value="<" data-testid="cmp-lt">
                      {t("thresholds.cmpLt")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center gap-2">
                <label className="text-sm text-muted-foreground w-24">
                  {t("thresholds.unit")}
                </label>
                <Input
                  className="w-40"
                  placeholder="%"
                  value={unit}
                  onChange={(e) => setUnit(e.target.value)}
                  disabled={!canEdit}
                  data-testid="catalog-unit"
                />
              </div>
              <div className="space-y-1">
                <label className="text-sm text-muted-foreground">
                  {t("thresholds.valueQuery")}
                </label>
                <textarea
                  className="h-20 w-full rounded-md border border-input bg-background p-2 text-sm font-mono"
                  placeholder={'avg_over_time(mem_used{cmdb_ci="{{cmdb_ci}}"}[5m])'}
                  value={valueQuery}
                  onChange={(e) => setValueQuery(e.target.value)}
                  disabled={!canEdit}
                  data-testid="catalog-value-query"
                />
                <p className="text-xs text-muted-foreground">{t("thresholds.valueQueryHint")}</p>
              </div>
              {canEdit && (
                <Button
                  disabled={saveCatalog.isPending}
                  onClick={() =>
                    saveCatalog.mutate(undefined, {
                      onError: fail,
                      onSuccess: () => toast({ title: t("common.success") }),
                    })
                  }
                  data-testid="catalog-save"
                >
                  {t("common.save")}
                </Button>
              )}
            </div>
          ) : (
            <div className="flex items-center justify-center text-sm text-muted-foreground" data-testid="catalog-noselect">
              {t("thresholds.selectRule")}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Threshold overrides */}
      <Card data-testid="overrides-card">
        <CardHeader>
          <CardTitle className="text-base">{t("thresholds.overrides")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          {/* pulled-rule picker: choose the alertname */}
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">{t("thresholds.pulledHelp")}</p>
            <div className="relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder={t("thresholds.searchRules")}
                value={ovrSearch}
                onChange={(e) => setOvrSearch(e.target.value)}
                data-testid="pulled-search"
              />
            </div>
            <div className="max-h-64 overflow-y-auto rounded-md border border-border/60" data-testid="pulled-list">
              {filteredPulled.map((r) => (
                <button
                  key={`${r.group}/${r.alertname}`}
                  type="button"
                  onClick={() => setOvrAlert(r.alertname)}
                  data-testid="pulled-rule"
                  className={`flex w-full flex-col gap-0.5 px-3 py-2 text-left text-sm hover:bg-accent ${
                    ovrAlert === r.alertname ? "bg-accent text-accent-foreground" : ""
                  }`}
                >
                  <span className="flex items-center justify-between">
                    <span className="font-mono">{r.alertname}</span>
                    {r.severity && <SeverityBadge severity={r.severity} />}
                  </span>
                  <span className="truncate font-mono text-xs text-muted-foreground">
                    {r.expr}
                  </span>
                </button>
              ))}
              {filteredPulled.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground" data-testid="pulled-empty">
                  {pulled.isLoading ? t("common.loading") : t("thresholds.noRules")}
                </div>
              )}
            </div>
          </div>

          {/* override form + list */}
          <div className="space-y-4">
            {canEdit && (
              <div className="space-y-3 rounded-md border border-border/60 bg-muted/20 p-3" data-testid="override-form">
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">{t("thresholds.rule")}</label>
                  <div className="font-mono text-sm" data-testid="ovr-selected">
                    {ovrAlert ?? <span className="text-muted-foreground">{t("thresholds.selectRule")}</span>}
                  </div>
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">{t("thresholds.target")}</label>
                  <Select value={targetKind} onValueChange={(v) => setTargetKind(v as TargetKind)}>
                    <SelectTrigger className="w-48" data-testid="ovr-target-kind">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="cmdb_ci" data-testid="target-cmdb">
                        {t("thresholds.targetCmdb")}
                      </SelectItem>
                      <SelectItem value="label" data-testid="target-label">
                        {t("thresholds.targetLabel")}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                {targetKind === "cmdb_ci" ? (
                  <div className="space-y-1">
                    <label className="text-xs text-muted-foreground">cmdb_ci</label>
                    <Input
                      className="font-mono"
                      placeholder="cmdb_ci"
                      value={cmdb}
                      onChange={(e) => setCmdb(e.target.value)}
                      data-testid="ovr-cmdb"
                    />
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <div className="flex-1 space-y-1">
                      <label className="text-xs text-muted-foreground">{t("thresholds.labelKey")}</label>
                      <Input
                        className="font-mono"
                        placeholder="severity"
                        value={labelKey}
                        onChange={(e) => setLabelKey(e.target.value)}
                        data-testid="ovr-label-key"
                      />
                    </div>
                    <div className="flex-1 space-y-1">
                      <label className="text-xs text-muted-foreground">{t("thresholds.labelValue")}</label>
                      <Input
                        className="font-mono"
                        placeholder="critical"
                        value={labelValue}
                        onChange={(e) => setLabelValue(e.target.value)}
                        data-testid="ovr-label-value"
                      />
                    </div>
                  </div>
                )}
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">
                    {t("thresholds.value")}
                    {selectedRuleMeta?.unit ? ` (${selectedRuleMeta.unit})` : ""}
                  </label>
                  <Input
                    className="w-28"
                    type="number"
                    placeholder="95"
                    value={ovrValue}
                    onChange={(e) => setOvrValue(e.target.value)}
                    data-testid="ovr-value"
                  />
                </div>
                <Button
                  disabled={!canSubmitOverride || createOverride.isPending}
                  onClick={() =>
                    createOverride.mutate(undefined, {
                      onError: fail,
                      onSuccess: () => toast({ title: t("thresholds.added") }),
                    })
                  }
                  data-testid="ovr-create"
                >
                  {t("thresholds.addOverride")}
                </Button>
              </div>
            )}

            <ul className="space-y-1" data-testid="overrides-list">
              {(overrides.data?.data ?? []).map((o) => {
                const meta = catalogMeta(o.alertname);
                return (
                  <li
                    key={o.id}
                    data-testid="override-row"
                    className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm"
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="font-mono">{o.alertname}</span>
                      {o.target_cmdb_ci ? (
                        <span className="flex items-center gap-1.5">
                          <Badge variant="outline">{t("thresholds.targetCmdb")}</Badge>
                          <span className="font-mono text-xs text-muted-foreground">
                            {o.target_cmdb_ci}
                          </span>
                        </span>
                      ) : (
                        <span className="flex items-center gap-1.5">
                          <Badge variant="outline">{t("thresholds.targetLabel")}</Badge>
                          <span className="font-mono text-xs text-muted-foreground">
                            {o.target_label_key}={o.target_label_value}
                          </span>
                        </span>
                      )}
                      <span className="text-muted-foreground">·</span>
                      <span className="font-medium" data-testid="override-value">
                        {meta?.comparator ?? ""} {o.value}
                        {meta?.unit ?? ""}
                      </span>
                    </span>
                    {canEdit && (
                      <Button
                        size="icon"
                        variant="ghost"
                        onClick={() => deleteOverride.mutate(o.id, { onError: fail })}
                        data-testid="override-delete"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    )}
                  </li>
                );
              })}
              {overrides.data?.data.length === 0 && (
                <li className="text-sm text-muted-foreground" data-testid="overrides-empty">
                  {t("thresholds.noOverrides")}
                </li>
              )}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
