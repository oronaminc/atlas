import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  useApiMutation,
  useNotificationSettings,
  useRecipients,
} from "@/api/queries";
import { FormField } from "@/components/common/form-field";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";

export function NotificationSettingsCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const settings = useNotificationSettings();

  const [token, setToken] = useState("");
  const [rate, setRate] = useState("");
  const [groupQuota, setGroupQuota] = useState("");
  const [globalQuota, setGlobalQuota] = useState("");
  const [softcap, setSoftcap] = useState("");

  useEffect(() => {
    const data = settings.data?.data;
    if (data) {
      setRate(String(data.telegram_rate_per_second));
      setGroupQuota(String(data.quota_group_per_hour));
      setGlobalQuota(String(data.quota_global_per_day));
      setSoftcap(String(data.pending_softcap));
    }
  }, [settings.data]);

  const tokenConfigured = settings.data?.data.telegram_bot_token != null;

  const save = useApiMutation(
    () =>
      api.patch("/notification-settings", {
        ...(token ? { telegram_bot_token: token } : {}),
        telegram_rate_per_second: Number(rate),
        quota_group_per_hour: Number(groupQuota),
        quota_global_per_day: Number(globalQuota),
        pending_softcap: Number(softcap),
      }),
    ["notification-settings"],
    () => {
      setToken("");
      toast({ title: t("common.success") });
    },
  );

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle className="text-base">{t("notify.settings")}</CardTitle>
        <CardDescription>{t("notify.settingsHelp")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <FormField
          label={t("notify.botToken")}
          htmlFor="bot-token"
          description={tokenConfigured ? t("notify.tokenSet") : t("notify.tokenUnset")}
        >
          <Input
            id="bot-token"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder={tokenConfigured ? "********" : "123456:ABC-DEF..."}
          />
        </FormField>
        <div className="grid gap-4 sm:grid-cols-3">
          <FormField label={t("notify.ratePerSecond")} htmlFor="tg-rate" required>
            <Input
              id="tg-rate"
              type="number"
              min={1}
              value={rate}
              onChange={(e) => setRate(e.target.value)}
            />
          </FormField>
          <FormField label={t("notify.groupQuota")} htmlFor="q-group" required>
            <Input
              id="q-group"
              type="number"
              min={1}
              value={groupQuota}
              onChange={(e) => setGroupQuota(e.target.value)}
            />
          </FormField>
          <FormField label={t("notify.globalQuota")} htmlFor="q-global" required>
            <Input
              id="q-global"
              type="number"
              min={1}
              value={globalQuota}
              onChange={(e) => setGlobalQuota(e.target.value)}
            />
          </FormField>
        </div>
        <FormField
          label={t("notify.pendingSoftcap")}
          htmlFor="pending-softcap"
          description={t("notify.pendingSoftcapHelp")}
        >
          <Input
            id="pending-softcap"
            type="number"
            min={1}
            value={softcap}
            onChange={(e) => setSoftcap(e.target.value)}
          />
        </FormField>
        <Button
          onClick={() => save.mutate(undefined)}
          disabled={save.isPending || !(Number(rate) >= 1)}
        >
          {t("common.save")}
        </Button>
        {save.isError && (
          <p className="text-sm text-destructive">
            {save.error instanceof Error ? save.error.message : t("common.error")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function RecipientsCard() {
  const { t } = useTranslation();
  const recipients = useRecipients();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("notify.recipients")}</CardTitle>
        <CardDescription>{t("notify.recipientsHelp")}</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("common.name")}</TableHead>
              <TableHead>{t("auth.email")}</TableHead>
              <TableHead>Telegram</TableHead>
              <TableHead>{t("nav.groups")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {(recipients.data?.data ?? []).map((r) => (
              <TableRow key={r.user_id}>
                <TableCell className="font-medium">{r.username}</TableCell>
                <TableCell className="text-muted-foreground">{r.email}</TableCell>
                <TableCell>
                  {r.telegram_chat_id ? (
                    <Badge variant="success">{r.telegram_chat_id}</Badge>
                  ) : (
                    <Badge variant="secondary">—</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    {r.groups.map((g) => (
                      <Badge key={g} variant="outline">
                        {g}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
