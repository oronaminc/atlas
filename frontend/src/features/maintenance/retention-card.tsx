/** Retention policy: days per data class (0 = keep forever) + archive toggle.
 *  Admin-only (the /settings route is admin-gated). */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation } from "@/api/queries";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";

interface Retention {
  alert_events_days: number;
  incidents_days: number;
  notifications_days: number;
  audit_days: number;
  archive_enabled: boolean;
}

const DAY_FIELDS: { key: keyof Retention; labelKey: string }[] = [
  { key: "alert_events_days", labelKey: "retention.alertEvents" },
  { key: "incidents_days", labelKey: "retention.incidents" },
  { key: "notifications_days", labelKey: "retention.notifications" },
  { key: "audit_days", labelKey: "retention.audit" },
];

export function RetentionCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const config = useQuery({
    queryKey: ["retention-config"],
    queryFn: () => api.get<Retention>("/retention-config"),
  });

  const [form, setForm] = useState<Retention | null>(null);
  useEffect(() => {
    if (config.data) setForm(config.data.data);
  }, [config.data]);

  const save = useApiMutation(
    () => api.patch<Retention>("/retention-config", form),
    ["retention-config"],
    () => toast({ title: t("common.success") }),
  );

  if (!form) return null;

  return (
    <Card className="max-w-xl" data-testid="retention-card">
      <CardHeader>
        <CardTitle className="text-base">{t("retention.title")}</CardTitle>
        <CardDescription>{t("retention.help")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          {DAY_FIELDS.map(({ key, labelKey }) => (
            <div key={key}>
              <Label htmlFor={`ret-${key}`}>{t(labelKey)}</Label>
              <Input
                id={`ret-${key}`}
                type="number"
                min={0}
                value={form[key] as number}
                onChange={(e) => setForm({ ...form, [key]: Number(e.target.value) })}
              />
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="ret-archive"
            checked={form.archive_enabled}
            onCheckedChange={(v) => setForm({ ...form, archive_enabled: v })}
          />
          <Label htmlFor="ret-archive">{t("retention.archive")}</Label>
        </div>
        <Button
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
          disabled={save.isPending}
          data-testid="retention-save"
        >
          {t("common.save")}
        </Button>
      </CardContent>
    </Card>
  );
}
