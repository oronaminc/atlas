/** IMP admin: view/configure the incident-formation criteria (v1: single rule —
 *  group by cmdb_service_l2_code, severity-aware formation). label_keys are
 *  display-only; only the timing/size knobs are editable. */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useGroupingRules } from "@/api/queries";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";

export function GroupingRulesPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin");
  const rules = useGroupingRules();
  const rule = rules.data?.data?.[0];

  const [windowSeconds, setWindowSeconds] = useState("");
  const [minGroupSize, setMinGroupSize] = useState("");
  const [dedupWindowSeconds, setDedupWindowSeconds] = useState("");
  const [criticalImmediate, setCriticalImmediate] = useState(true);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (!rule) return;
    setWindowSeconds(String(rule.window_seconds));
    setMinGroupSize(String(rule.min_group_size));
    setDedupWindowSeconds(String(rule.dedup_window_seconds));
    setCriticalImmediate(rule.critical_immediate);
    setEnabled(rule.enabled);
  }, [rule]);

  const save = useApiMutation(
    () =>
      api.patch(`/grouping-rules/${rule!.id}`, {
        enabled,
        window_seconds: Number(windowSeconds),
        min_group_size: Number(minGroupSize),
        dedup_window_seconds: Number(dedupWindowSeconds),
        critical_immediate: criticalImmediate,
      }),
    ["grouping-rules"],
    () => toast({ title: t("common.success") }),
  );

  return (
    <div data-testid="grouping-rules-page" className="space-y-4">
      <PageHeader title={t("nav.groupingRules")} description={t("groupingRules.description")} />
      {rule && (
        <Card className="max-w-2xl">
          <CardHeader>
            <CardTitle className="text-base">{rule.name}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Field label={t("groupingRules.labelKeys")}>
              <div className="flex flex-wrap gap-1" data-testid="label-keys">
                {rule.label_keys.length === 0 ? (
                  <span className="text-sm text-muted-foreground">-</span>
                ) : (
                  rule.label_keys.map((k) => (
                    <Badge key={k} variant="outline">
                      {k}
                    </Badge>
                  ))
                )}
              </div>
            </Field>
            <Field label={t("groupingRules.window")}>
              <Input
                type="number"
                value={windowSeconds}
                onChange={(e) => setWindowSeconds(e.target.value)}
                disabled={!canEdit}
                data-testid="window-seconds"
              />
            </Field>
            <Field label={t("groupingRules.minGroupSize")}>
              <Input
                type="number"
                value={minGroupSize}
                onChange={(e) => setMinGroupSize(e.target.value)}
                disabled={!canEdit}
                data-testid="min-group-size"
              />
            </Field>
            <Field label={t("groupingRules.dedupWindow")}>
              <Input
                type="number"
                value={dedupWindowSeconds}
                onChange={(e) => setDedupWindowSeconds(e.target.value)}
                disabled={!canEdit}
                data-testid="dedup-window-seconds"
              />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <Switch
                checked={criticalImmediate}
                onCheckedChange={setCriticalImmediate}
                disabled={!canEdit}
                data-testid="critical-immediate"
              />
              {t("groupingRules.criticalImmediate")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={enabled} onCheckedChange={setEnabled} disabled={!canEdit} />
              {t("common.enabled")}
            </label>
            {canEdit && (
              <Button
                disabled={save.isPending}
                onClick={() =>
                  save.mutate(undefined, {
                    onError: (e) =>
                      toast({
                        variant: "destructive",
                        title: t("common.failed"),
                        description: e instanceof Error ? e.message : String(e),
                      }),
                  })
                }
                data-testid="save-rule"
              >
                {t("common.save")}
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-40 text-sm text-muted-foreground">{label}</span>
      <div className="flex-1">{children}</div>
    </div>
  );
}
