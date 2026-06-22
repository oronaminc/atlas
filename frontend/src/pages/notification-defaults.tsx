/** IMP admin: default per-incident notification channel toggles applied to new
 *  incidents at creation (email/telegram/oncall). */

import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useNotificationDefaults } from "@/api/queries";
import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";

export function NotificationDefaultsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin");
  const defaults = useNotificationDefaults();
  const d = defaults.data?.data;

  const patch = useApiMutation(
    (body: Record<string, boolean>) => api.patch("/notification-defaults", body),
    ["notification-defaults"],
  );

  const fail = (e: unknown) =>
    toast({
      variant: "destructive",
      title: t("common.failed"),
      description: e instanceof Error ? e.message : String(e),
    });

  return (
    <div data-testid="notification-defaults-page" className="space-y-4">
      <PageHeader
        title={t("nav.notificationDefaults")}
        description={t("notificationDefaults.description")}
      />
      {d && (
        <Card className="max-w-md">
          <CardHeader>
            <CardTitle className="text-base">{t("notificationDefaults.title")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {(["default_email", "default_telegram", "default_oncall"] as const).map((key) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <Switch
                  checked={d[key]}
                  disabled={!canEdit || patch.isPending}
                  onCheckedChange={(v) => patch.mutate({ [key]: v }, { onError: fail })}
                  data-testid={`default-${key}`}
                />
                {t(`notificationDefaults.${key}`)}
              </label>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
