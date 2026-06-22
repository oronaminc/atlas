/** IMP admin: view/configure the topology grouping criteria (v1: single rule —
 *  group by cmdb_service_l2_code, severity-aware formation). */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useGroupingRules } from "@/api/queries";
import { PageHeader } from "@/components/layout/page-header";
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

  const [labelKeys, setLabelKeys] = useState("");
  const [windowSeconds, setWindowSeconds] = useState("");
  const [minGroupSize, setMinGroupSize] = useState("");
  const [criticalImmediate, setCriticalImmediate] = useState(true);
  const [enabled, setEnabled] = useState(true);

  useEffect(() => {
    if (!rule) return;
    setLabelKeys(rule.label_keys.join(", "));
    setWindowSeconds(String(rule.window_seconds));
    setMinGroupSize(String(rule.min_group_size));
    setCriticalImmediate(rule.critical_immediate);
    setEnabled(rule.enabled);
  }, [rule]);

  const save = useApiMutation(
    () =>
      api.patch(`/grouping-rules/${rule!.id}`, {
        enabled,
        label_keys: labelKeys.split(",").map((s) => s.trim()).filter(Boolean),
        window_seconds: Number(windowSeconds),
        min_group_size: Number(minGroupSize),
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
              <Input
                value={labelKeys}
                onChange={(e) => setLabelKeys(e.target.value)}
                disabled={!canEdit}
                data-testid="label-keys"
              />
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
