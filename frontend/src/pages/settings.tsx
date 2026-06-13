import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useCorrelationConfig } from "@/api/queries";
import { FormField } from "@/components/common/form-field";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import {
  NotificationRoutesCard,
  NotificationSettingsCard,
  RecipientsCard,
} from "@/features/notifications/notification-admin";
import { TenantsCard } from "@/features/tenants/tenants-card";
import { useAuth } from "@/hooks/use-auth";

export function SettingsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { user: me } = useAuth();
  const isHq = me?.tenant_id == null;
  const config = useCorrelationConfig();

  const [dedupWindow, setDedupWindow] = useState("");
  const [correlationWindow, setCorrelationWindow] = useState("");
  const [groupAttrs, setGroupAttrs] = useState("");

  useEffect(() => {
    const data = config.data?.data;
    if (data) {
      setDedupWindow(String(data.dedup_window_seconds));
      setCorrelationWindow(String(data.correlation_window_seconds));
      setGroupAttrs(data.group_attrs.join(", "));
    }
  }, [config.data]);

  const save = useApiMutation(
    () =>
      api.patch("/correlation-config", {
        dedup_window_seconds: Number(dedupWindow),
        correlation_window_seconds: Number(correlationWindow),
        group_attrs: groupAttrs
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    ["correlation-config"],
    () => toast({ title: t("common.success") }),
  );

  const invalid =
    !(Number(dedupWindow) >= 1) ||
    !(Number(correlationWindow) >= 1) ||
    groupAttrs.split(",").filter((s) => s.trim()).length === 0;

  if (config.isLoading) return <LoadingSpinner />;

  return (
    <div>
      <PageHeader title={t("settings.title")} description={t("settings.description")} />
      <Card className="max-w-xl">
        <CardHeader>
          <CardTitle className="text-base">{t("settings.correlation")}</CardTitle>
          <CardDescription>{t("settings.correlationHelp")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <FormField
            label={t("settings.dedupWindow")}
            htmlFor="dedup-window"
            description={t("settings.seconds")}
            required
          >
            <Input
              id="dedup-window"
              type="number"
              min={1}
              value={dedupWindow}
              onChange={(e) => setDedupWindow(e.target.value)}
            />
          </FormField>
          <FormField
            label={t("settings.correlationWindow")}
            htmlFor="correlation-window"
            description={t("settings.seconds")}
            required
          >
            <Input
              id="correlation-window"
              type="number"
              min={1}
              value={correlationWindow}
              onChange={(e) => setCorrelationWindow(e.target.value)}
            />
          </FormField>
          <FormField
            label={t("settings.groupAttrs")}
            htmlFor="group-attrs"
            description={t("settings.groupAttrsHelp")}
            required
          >
            <Input
              id="group-attrs"
              value={groupAttrs}
              onChange={(e) => setGroupAttrs(e.target.value)}
              placeholder="host, service, cluster"
            />
          </FormField>
          <Button onClick={() => save.mutate(undefined)} disabled={invalid || save.isPending}>
            {t("common.save")}
          </Button>
          {save.isError && (
            <p className="text-sm text-destructive">
              {save.error instanceof Error ? save.error.message : t("common.error")}
            </p>
          )}
        </CardContent>
      </Card>

      <div className="mt-6 space-y-6">
        {isHq && <TenantsCard />}
        <NotificationSettingsCard />
        <NotificationRoutesCard />
        <RecipientsCard />
      </div>
    </div>
  );
}
