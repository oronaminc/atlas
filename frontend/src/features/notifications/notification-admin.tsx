import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  useApiMutation,
  useGroups,
  useNotificationRoutes,
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/hooks/use-toast";
import type { NotificationRoute } from "@/types";

export function NotificationSettingsCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const settings = useNotificationSettings();

  const [token, setToken] = useState("");
  const [rate, setRate] = useState("");
  const [groupQuota, setGroupQuota] = useState("");
  const [globalQuota, setGlobalQuota] = useState("");

  useEffect(() => {
    const data = settings.data?.data;
    if (data) {
      setRate(String(data.telegram_rate_per_second));
      setGroupQuota(String(data.quota_group_per_hour));
      setGlobalQuota(String(data.quota_global_per_day));
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

export function NotificationRoutesCard() {
  const { t } = useTranslation();
  const routes = useNotificationRoutes();
  const groups = useGroups({ limit: "100" });

  const [groupId, setGroupId] = useState("");
  const [minSeverity, setMinSeverity] = useState("warning");
  const [telegram, setTelegram] = useState(true);
  const [email, setEmail] = useState(false);

  const groupName = (id: string) =>
    groups.data?.data.find((g) => g.id === id)?.name ?? id.slice(0, 8);

  const create = useApiMutation(
    () =>
      api.post("/notification-routes", {
        group_id: groupId,
        min_severity: minSeverity,
        channels: [...(telegram ? ["telegram"] : []), ...(email ? ["email"] : [])],
      }),
    ["notification-routes"],
    () => setGroupId(""),
  );

  const toggle = useApiMutation(
    (route: NotificationRoute) =>
      api.patch(`/notification-routes/${route.id}`, { enabled: !route.enabled }),
    ["notification-routes"],
  );

  const remove = useApiMutation(
    (route: NotificationRoute) => api.delete(`/notification-routes/${route.id}`),
    ["notification-routes"],
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{t("notify.routes")}</CardTitle>
        <CardDescription>{t("notify.routesHelp")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("nav.groups")}</TableHead>
              <TableHead>{t("notify.minSeverity")}</TableHead>
              <TableHead>{t("notify.channels")}</TableHead>
              <TableHead>{t("common.enabled")}</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {(routes.data?.data ?? []).map((route) => (
              <TableRow key={route.id}>
                <TableCell className="font-medium">{groupName(route.group_id)}</TableCell>
                <TableCell>
                  <Badge variant="outline">{route.min_severity}</Badge>
                </TableCell>
                <TableCell>
                  <div className="flex gap-1">
                    {route.channels.map((c) => (
                      <Badge key={c} variant="secondary">
                        {c}
                      </Badge>
                    ))}
                  </div>
                </TableCell>
                <TableCell>
                  <Switch
                    checked={route.enabled}
                    onCheckedChange={() => toggle.mutate(route)}
                  />
                </TableCell>
                <TableCell>
                  <Button variant="ghost" size="icon" onClick={() => remove.mutate(route)}>
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        <div className="flex flex-wrap items-end gap-2">
          <Select value={groupId} onValueChange={setGroupId}>
            <SelectTrigger className="w-48">
              <SelectValue placeholder={t("notify.selectGroup")} />
            </SelectTrigger>
            <SelectContent>
              {(groups.data?.data ?? []).map((g) => (
                <SelectItem key={g.id} value={g.id}>
                  {g.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={minSeverity} onValueChange={setMinSeverity}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="critical">critical</SelectItem>
              <SelectItem value="warning">warning</SelectItem>
              <SelectItem value="info">info</SelectItem>
            </SelectContent>
          </Select>
          <label className="flex items-center gap-1 text-sm">
            <Switch checked={telegram} onCheckedChange={setTelegram} /> Telegram
          </label>
          <label className="flex items-center gap-1 text-sm">
            <Switch checked={email} onCheckedChange={setEmail} /> Email
          </label>
          <Button
            onClick={() => create.mutate(undefined)}
            disabled={!groupId || (!telegram && !email) || create.isPending}
          >
            {t("common.create")}
          </Button>
        </div>
        {create.isError && (
          <p className="text-sm text-destructive">
            {create.error instanceof Error ? create.error.message : t("common.error")}
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
