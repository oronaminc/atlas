/** Threshold overrides — NO PromQL model.
 *
 *  The user picks an alertname from the rules PULLED from the Mimir Ruler
 *  (read-only), then sets a threshold for a target:
 *    - Per-service: a cmdb_service_l2_code the user's groups own
 *      (target_label_key = "cmdb_service_l2_code", value = the code), OR
 *    - Per-server: a single cmdb_ci (autocompleted from /labels/cmdb_ci/values).
 *
 *  A default↔custom Switch shows the rule's base_threshold read-only by
 *  default; toggling on reveals a single NUMBER input. There is no expr /
 *  value_query / comparator input anywhere — comparator is display-only from
 *  the pulled rule. */

import { useEffect, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { Search, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  useApiMutation,
  useLabelValues,
  useRulesPulled,
  useThresholdOverrides,
} from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layout/page-header";
import { SeverityBadge } from "@/components/common/status-badge";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import type { PulledRule } from "@/types";

const SERVICE_LABEL_KEY = "cmdb_service_l2_code";
type TargetKind = "service" | "server";

/** Union the cmdb_service_l2_code values across all of the current user's
 *  groups — these are the services the user is allowed to set overrides for. */
function useMyServiceCodes(groupIds: string[]): { codes: string[]; loading: boolean } {
  const results = useQueries({
    queries: groupIds.map((id) => ({
      queryKey: ["group-service-codes", id],
      queryFn: () => api.get<{ codes: string[] }>(`/groups/${id}/service-codes`),
      staleTime: 5 * 60_000,
    })),
  });
  const codes = useMemo(() => {
    const set = new Set<string>();
    for (const r of results) for (const c of r.data?.data.codes ?? []) set.add(c);
    return [...set].sort();
  }, [results]);
  return { codes, loading: results.some((r) => r.isLoading) };
}

export function ThresholdsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole, user } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const pulled = useRulesPulled();
  const overrides = useThresholdOverrides();
  const cmdbCiValues = useLabelValues("cmdb_ci");

  const groupIds = useMemo(
    () => [...new Set((user?.groups ?? []).map((g) => g.group_id))],
    [user?.groups],
  );
  const { codes: serviceCodes } = useMyServiceCodes(groupIds);

  const fail = (e: unknown) =>
    toast({
      variant: "destructive",
      title: t("common.failed"),
      description: e instanceof Error ? e.message : String(e),
    });

  // --- rule picker ---
  const pulledRules = useMemo(() => pulled.data?.data ?? [], [pulled.data]);
  const [ruleSearch, setRuleSearch] = useState("");
  const [selected, setSelected] = useState<PulledRule | null>(null);
  const filteredRules = useMemo(() => {
    const q = ruleSearch.trim().toLowerCase();
    return q
      ? pulledRules.filter((r) => r.alertname.toLowerCase().includes(q))
      : pulledRules;
  }, [pulledRules, ruleSearch]);

  // --- target + value ---
  const [targetKind, setTargetKind] = useState<TargetKind>("service");
  const [serviceCode, setServiceCode] = useState("");
  const [cmdbCi, setCmdbCi] = useState("");
  const [custom, setCustom] = useState(false);
  const [value, setValue] = useState("");

  // reset the editor when the selected rule changes
  useEffect(() => {
    setCustom(false);
    setValue(selected?.base_threshold != null ? String(selected.base_threshold) : "");
  }, [selected]);

  const createOverride = useApiMutation(
    () =>
      api.post("/threshold-overrides", {
        alertname: selected?.alertname,
        ...(targetKind === "server"
          ? { target_cmdb_ci: cmdbCi }
          : { target_label_key: SERVICE_LABEL_KEY, target_label_value: serviceCode }),
        value: Number(value),
      }),
    ["threshold-overrides"],
    () => {
      setCmdbCi("");
      setServiceCode("");
      setCustom(false);
      setValue(selected?.base_threshold != null ? String(selected.base_threshold) : "");
    },
  );
  const deleteOverride = useApiMutation(
    (id: string) => api.delete(`/threshold-overrides/${id}`),
    ["threshold-overrides"],
  );

  const effectiveValue = custom
    ? value
    : selected?.base_threshold != null
      ? String(selected.base_threshold)
      : "";
  const canSubmit =
    !!selected &&
    effectiveValue.trim() !== "" &&
    !Number.isNaN(Number(effectiveValue)) &&
    (targetKind === "server" ? !!cmdbCi.trim() : !!serviceCode.trim());

  const submit = () =>
    createOverride.mutate(undefined, {
      onError: fail,
      onSuccess: () => toast({ title: t("thresholds.added") }),
    });

  return (
    <div data-testid="thresholds-page" className="space-y-6">
      <PageHeader title={t("thresholds.title")} description={t("thresholds.description")} />

      <Card data-testid="override-editor-card">
        <CardHeader>
          <CardTitle className="text-base">{t("thresholds.editor")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          {/* rule picker */}
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">{t("thresholds.ruleSelect")}</p>
            <div className="relative">
              <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder={t("thresholds.searchRules")}
                value={ruleSearch}
                onChange={(e) => setRuleSearch(e.target.value)}
                data-testid="rule-search"
              />
            </div>
            <div
              className="max-h-72 overflow-y-auto rounded-md border border-border/60"
              data-testid="rule-list"
            >
              {filteredRules.map((r) => (
                <button
                  key={`${r.group_name}/${r.alertname}`}
                  type="button"
                  onClick={() => setSelected(r)}
                  data-testid="rule-pick"
                  className={`flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-accent ${
                    selected?.alertname === r.alertname ? "bg-accent text-accent-foreground" : ""
                  }`}
                >
                  <span className="font-mono">{r.alertname}</span>
                  <span className="flex items-center gap-2">
                    {r.base_threshold != null && (
                      <span className="font-mono text-xs text-muted-foreground">
                        {r.comparator ?? ""} {r.base_threshold}
                      </span>
                    )}
                    {r.severity && <SeverityBadge severity={r.severity} />}
                  </span>
                </button>
              ))}
              {filteredRules.length === 0 && (
                <div className="px-3 py-2 text-sm text-muted-foreground" data-testid="rule-empty">
                  {pulled.isLoading ? t("common.loading") : t("thresholds.noRules")}
                </div>
              )}
            </div>
          </div>

          {/* override form */}
          {canEdit ? (
            <div className="space-y-3 rounded-md border border-border/60 bg-muted/20 p-3" data-testid="override-form">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">{t("thresholds.rule")}</label>
                <div className="font-mono text-sm" data-testid="ovr-selected">
                  {selected?.alertname ?? (
                    <span className="text-muted-foreground">{t("thresholds.selectRule")}</span>
                  )}
                </div>
              </div>

              {/* target kind toggle */}
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">{t("thresholds.target")}</label>
                <Select value={targetKind} onValueChange={(v) => setTargetKind(v as TargetKind)}>
                  <SelectTrigger className="w-52" data-testid="ovr-target-kind">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="service" data-testid="target-service">
                      {t("thresholds.perService")}
                    </SelectItem>
                    <SelectItem value="server" data-testid="target-server">
                      {t("thresholds.perServer")}
                    </SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {targetKind === "service" ? (
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">{t("thresholds.serviceCode")}</label>
                  {serviceCodes.length > 0 ? (
                    <Select value={serviceCode} onValueChange={setServiceCode}>
                      <SelectTrigger data-testid="ovr-service">
                        <SelectValue placeholder={t("thresholds.selectService")} />
                      </SelectTrigger>
                      <SelectContent>
                        {serviceCodes.map((c) => (
                          <SelectItem key={c} value={c}>
                            {c}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    // no group service-codes resolved → free text entry
                    <Input
                      className="font-mono"
                      placeholder={SERVICE_LABEL_KEY}
                      value={serviceCode}
                      onChange={(e) => setServiceCode(e.target.value)}
                      data-testid="ovr-service-text"
                    />
                  )}
                </div>
              ) : (
                <div className="space-y-1">
                  <label className="text-xs text-muted-foreground">cmdb_ci</label>
                  <Input
                    className="font-mono"
                    placeholder="cmdb_ci"
                    list="cmdb-ci-values"
                    value={cmdbCi}
                    onChange={(e) => setCmdbCi(e.target.value)}
                    data-testid="ovr-cmdb"
                  />
                  <datalist id="cmdb-ci-values">
                    {(cmdbCiValues.data?.data ?? []).map((v) => (
                      <option key={v} value={v} />
                    ))}
                  </datalist>
                </div>
              )}

              {/* default ↔ custom threshold */}
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-xs text-muted-foreground">{t("thresholds.value")}</label>
                  <label className="flex items-center gap-2 text-xs">
                    {custom ? t("thresholds.customValue") : t("thresholds.defaultValue")}
                    <Switch
                      checked={custom}
                      onCheckedChange={setCustom}
                      disabled={!selected}
                      data-testid="ovr-custom-toggle"
                    />
                  </label>
                </div>
                {custom ? (
                  <Input
                    className="w-32"
                    type="number"
                    placeholder="95"
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    data-testid="ovr-value"
                  />
                ) : (
                  <div
                    className="w-32 rounded-md border border-border/60 bg-muted/40 px-3 py-2 font-mono text-sm text-muted-foreground"
                    data-testid="ovr-base"
                  >
                    {selected?.comparator ?? ""}{" "}
                    {selected?.base_threshold != null ? selected.base_threshold : "—"}
                  </div>
                )}
              </div>

              <Button
                disabled={!canSubmit || createOverride.isPending}
                onClick={submit}
                data-testid="ovr-create"
              >
                {t("thresholds.addOverride")}
              </Button>
            </div>
          ) : (
            <div className="flex items-center justify-center text-sm text-muted-foreground">
              {t("thresholds.readOnly")}
            </div>
          )}
        </CardContent>
      </Card>

      {/* existing overrides */}
      <Card data-testid="overrides-card">
        <CardHeader>
          <CardTitle className="text-base">{t("thresholds.overrides")}</CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-1" data-testid="overrides-list">
            {(overrides.data?.data ?? []).map((o) => (
              <li
                key={o.id}
                data-testid="override-row"
                className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono">{o.alertname}</span>
                  {o.target_cmdb_ci ? (
                    <span className="flex items-center gap-1.5">
                      <Badge variant="outline">{t("thresholds.perServer")}</Badge>
                      <span className="font-mono text-xs text-muted-foreground">
                        {o.target_cmdb_ci}
                      </span>
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5">
                      <Badge variant="outline">{t("thresholds.perService")}</Badge>
                      <span className="font-mono text-xs text-muted-foreground">
                        {o.target_label_key}={o.target_label_value}
                      </span>
                    </span>
                  )}
                  <span className="text-muted-foreground">·</span>
                  <span className="font-medium" data-testid="override-value">
                    {o.value}
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
            ))}
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
