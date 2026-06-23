/** Channel assignment (admin): each user GROUP owns its own notification
 *  channels — its telegram bot+chats, emails, and oncall webhook. Nothing is
 *  global. Fanout routes incident → groups mapped to its l2 → these channels. */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useGroupChannels, useGroups } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/hooks/use-toast";

const MASKED = "********";

export function ChannelAssignmentCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const groups = useGroups({ limit: "200" });
  const [groupId, setGroupId] = useState<string | null>(null);
  const channels = useGroupChannels(groupId);

  const fail = (e: unknown) =>
    toast({
      variant: "destructive",
      title: t("common.failed"),
      description: e instanceof Error ? e.message : String(e),
    });

  const del = useApiMutation(
    (id: string) => api.delete(`/channels/${id}`),
    ["group-channels"],
  );

  return (
    <Card className="p-4">
      <h2 className="mb-1 text-lg font-semibold">{t("channels.title")}</h2>
      <p className="mb-4 text-sm text-muted-foreground">{t("channels.help")}</p>

      <div className="mb-4 max-w-sm">
        <Select value={groupId ?? ""} onValueChange={setGroupId}>
          <SelectTrigger>
            <SelectValue placeholder={t("channels.selectGroup")} />
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

      {groupId && (
        <div className="space-y-3">
          <div className="space-y-1">
            {(channels.data?.data ?? []).map((c) => (
              <div
                key={c.id}
                className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 px-3 py-2 text-sm"
              >
                <span className="flex items-center gap-2">
                  <Badge variant="outline">{c.channel}</Badge>
                  <span className="font-mono text-xs">
                    {c.channel === "telegram" && `${c.chat_id} (bot ${MASKED})`}
                    {c.channel === "email" && c.email}
                    {c.channel === "oncall" && `webhook ${MASKED}`}
                  </span>
                  {!c.enabled && <Badge variant="secondary">{t("common.disabled")}</Badge>}
                </span>
                <Button size="sm" variant="ghost" onClick={() => del.mutate(c.id, { onError: fail })}>
                  {t("common.delete")}
                </Button>
              </div>
            ))}
            {channels.data?.data.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("channels.none")}</p>
            )}
          </div>
          <AddChannelForm groupId={groupId} onError={fail} />
        </div>
      )}
    </Card>
  );
}

function AddChannelForm({ groupId, onError }: { groupId: string; onError: (e: unknown) => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [channel, setChannel] = useState<"telegram" | "email" | "oncall">("telegram");
  const [botToken, setBotToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [email, setEmail] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");

  const add = useApiMutation(
    (body: Record<string, unknown>) => api.post(`/groups/${groupId}/channels`, body),
    ["group-channels"],
  );

  const submit = () => {
    const body: Record<string, unknown> = { channel };
    if (channel === "telegram") Object.assign(body, { bot_token: botToken, chat_id: chatId });
    if (channel === "email") body.email = email;
    if (channel === "oncall") body.webhook_url = webhookUrl;
    add.mutate(body, {
      onError,
      onSuccess: () => {
        setBotToken("");
        setChatId("");
        setEmail("");
        setWebhookUrl("");
        toast({ title: t("common.success") });
      },
    });
  };

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border border-dashed border-border/60 p-3">
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{t("channels.channel")}</span>
        <Select value={channel} onValueChange={(v) => setChannel(v as typeof channel)}>
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="telegram">Telegram</SelectItem>
            <SelectItem value="email">Email</SelectItem>
            <SelectItem value="oncall">OnCall</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {channel === "telegram" && (
        <>
          <LabeledInput label={t("channels.botToken")} value={botToken} onChange={setBotToken} type="password" />
          <LabeledInput label={t("channels.chatId")} value={chatId} onChange={setChatId} />
        </>
      )}
      {channel === "email" && (
        <LabeledInput label={t("channels.email")} value={email} onChange={setEmail} />
      )}
      {channel === "oncall" && (
        <LabeledInput label={t("channels.webhookUrl")} value={webhookUrl} onChange={setWebhookUrl} />
      )}
      <Button onClick={submit} disabled={add.isPending}>
        {t("channels.add")}
      </Button>
    </div>
  );
}

function LabeledInput({
  label,
  value,
  onChange,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <Input type={type} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}
