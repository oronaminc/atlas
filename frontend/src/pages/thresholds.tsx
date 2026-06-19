/** Threshold overrides (PR #2). Two cards:
 *  1. Rule catalog metadata — per-alertname comparator (>/<), unit, and the
 *     Mimir value_query (with a {{cmdb_ci}} slot). No value_query = pass-through
 *     (the ingest filter never suppresses, fail-open).
 *  2. Threshold overrides — per server (cmdb_ci) or group, with precedence
 *     server > group > default(none). The correlation worker fetches the live
 *     value from Mimir at filter time and suppresses below-threshold alerts. */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useServers } from "@/api/queries";
import { hostnameFromLabels, instanceFromLabels } from "@/lib/server-identity";
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

interface ServerGroup {
  id: string;
  name: string;
  member_count: number;
}
interface CatalogRule {
  alertname: string;
  comparator: ">" | "<" | null;
  unit: string | null;
  value_query: string | null;
}
interface Override {
  id: string;
  alertname: string;
  tier: "server" | "group";
  target_cmdb_ci: string | null;
  target_group_id: string | null;
  value: number;
}

export function ThresholdsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const groups = useQuery({
    queryKey: ["server-groups"],
    queryFn: () => api.get<ServerGroup[]>("/server-groups"),
  });
  const catalog = useQuery({
    queryKey: ["rule-catalog"],
    queryFn: () => api.get<CatalogRule[]>("/rule-catalog"),
  });
  const overrides = useQuery({
    queryKey: ["threshold-overrides"],
    queryFn: () => api.get<Override[]>("/threshold-overrides"),
  });
  // cmdb_ci -> server, so a server-tier override DISPLAYS hostname (+ip), not
  // the opaque cmdb_ci (which stays as secondary subtext).
  const serversQ = useServers({ limit: "100" });
  const serverByCmdb = useMemo(() => {
    const m = new Map<string, { host: string; ip?: string }>();
    for (const s of serversQ.data?.data ?? []) {
      if (s.cmdb_ci)
        m.set(s.cmdb_ci, {
          host: hostnameFromLabels(s.labels) ?? s.name,
          ip: instanceFromLabels(s.labels),
        });
    }
    return m;
  }, [serversQ.data]);
  const serverHost = (cmdb: string | null) =>
    (cmdb && serverByCmdb.get(cmdb)?.host) || cmdb || "—";
  const serverIp = (cmdb: string | null) => (cmdb && serverByCmdb.get(cmdb)?.ip) || undefined;

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

  // --- override create ---
  const [ovrAlert, setOvrAlert] = useState<string | null>(null);
  const [tier, setTier] = useState<"server" | "group">("server");
  const [cmdb, setCmdb] = useState("");
  const [ovrGroup, setOvrGroup] = useState("");
  const [ovrValue, setOvrValue] = useState("");

  const createOverride = useApiMutation(
    () =>
      api.post("/threshold-overrides", {
        alertname: ovrAlert,
        tier,
        target_cmdb_ci: tier === "server" ? cmdb : null,
        target_group_id: tier === "group" ? ovrGroup : null,
        value: Number(ovrValue),
      }),
    ["threshold-overrides"],
    () => {
      setCmdb("");
      setOvrValue("");
    },
  );
  const deleteOverride = useApiMutation(
    (id: string) => api.delete(`/threshold-overrides/${id}`),
    ["threshold-overrides"],
  );

  const groupName = (id: string | null) =>
    groups.data?.data.find((g) => g.id === id)?.name ?? id;

  const selectedRuleMeta = rules.find((r) => r.alertname === ovrAlert);
  const canSubmitOverride =
    !!ovrAlert &&
    ovrValue.trim() !== "" &&
    !Number.isNaN(Number(ovrValue)) &&
    ((tier === "server" && !!cmdb) || (tier === "group" && !!ovrGroup));

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
        <CardContent className="space-y-4">
          {canEdit && (
            <div className="flex flex-wrap items-end gap-2 rounded-md border border-border/60 bg-muted/20 p-3">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">{t("thresholds.rule")}</label>
                <Select value={ovrAlert ?? ""} onValueChange={setOvrAlert}>
                  <SelectTrigger className="w-56" data-testid="ovr-alert">
                    <SelectValue placeholder={t("thresholds.selectRule")} />
                  </SelectTrigger>
                  <SelectContent>
                    {rules.map((r) => (
                      <SelectItem key={r.alertname} value={r.alertname} data-testid="ovr-alert-option">
                        {r.alertname}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">{t("thresholds.tier")}</label>
                <Select value={tier} onValueChange={(v) => setTier(v as "server" | "group")}>
                  <SelectTrigger className="w-36" data-testid="ovr-tier">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="server" data-testid="tier-server">
                      {t("thresholds.tierServer")}
                    </SelectItem>
                    <SelectItem value="group" data-testid="tier-group">
                      {t("thresholds.tierGroup")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {tier === "server" ? (
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">cmdb_ci</label>
                  <Input
                    className="w-56 font-mono"
                    placeholder="cmdb_ci"
                    value={cmdb}
                    onChange={(e) => setCmdb(e.target.value)}
                    data-testid="ovr-cmdb"
                  />
                </div>
              ) : (
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">{t("thresholds.tierGroup")}</label>
                  <Select value={ovrGroup} onValueChange={setOvrGroup}>
                    <SelectTrigger className="w-48" data-testid="ovr-group">
                      <SelectValue placeholder={t("thresholds.selectGroup")} />
                    </SelectTrigger>
                    <SelectContent>
                      {(groups.data?.data ?? []).map((g) => (
                        <SelectItem key={g.id} value={g.id}>
                          {g.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
              const meta = rules.find((r) => r.alertname === o.alertname);
              return (
                <li
                  key={o.id}
                  data-testid="override-row"
                  className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-mono">{o.alertname}</span>
                    <Badge variant="outline">{t(`thresholds.tier${o.tier === "server" ? "Server" : "Group"}`)}</Badge>
                    {o.tier === "server" ? (
                      <span className="flex items-center gap-1.5">
                        <span className="font-medium">{serverHost(o.target_cmdb_ci)}</span>
                        {serverIp(o.target_cmdb_ci) && (
                          <span className="font-mono text-xs text-muted-foreground">
                            {serverIp(o.target_cmdb_ci)}
                          </span>
                        )}
                        <span className="font-mono text-[10px] text-muted-foreground/70">
                          {o.target_cmdb_ci}
                        </span>
                      </span>
                    ) : (
                      <span className="font-medium text-muted-foreground">
                        {groupName(o.target_group_id)}
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
        </CardContent>
      </Card>
    </div>
  );
}
