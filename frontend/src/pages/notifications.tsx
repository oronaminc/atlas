import { useState } from "react";
import { BellOff, Plus, Send, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  useApiMutation,
  usePolicies,
  useReceivers,
  useSilences,
} from "@/api/queries";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTable, type Column } from "@/components/common/data-table";
import { FormField } from "@/components/common/form-field";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";
import type { NotificationPolicy, Receiver, Silence } from "@/types";

export function NotificationsPage() {
  const { t } = useTranslation();
  return (
    <div>
      <PageHeader title={t("nav.notifications")} />
      <Tabs defaultValue="receivers">
        <TabsList>
          <TabsTrigger value="receivers">Receivers</TabsTrigger>
          <TabsTrigger value="policies">Policies</TabsTrigger>
          <TabsTrigger value="silences">Silences</TabsTrigger>
        </TabsList>
        <TabsContent value="receivers">
          <ReceiversTab />
        </TabsContent>
        <TabsContent value="policies">
          <PoliciesTab />
        </TabsContent>
        <TabsContent value="silences">
          <SilencesTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function ReceiversTab() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const canTest = hasRole("admin", "editor"); // test-send is require_editor on the backend
  const receivers = useReceivers();

  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<Receiver | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("slack");
  const [url, setUrl] = useState("");

  const create = useApiMutation(
    () => api.post("/receivers", { name, type, config: { url } }),
    ["receivers"],
    () => {
      setCreateOpen(false);
      setName("");
      setUrl("");
    },
  );

  const remove = useApiMutation(
    (r: Receiver) => api.delete(`/receivers/${r.id}`),
    ["receivers"],
    () => setDeleting(null),
  );

  const test = useApiMutation(
    (r: Receiver) => api.post<{ ok: boolean; error?: string }>(`/receivers/${r.id}/test`),
    [],
    (res) => {
      if (res.data.ok) toast({ title: t("common.success") });
      else
        toast({
          variant: "destructive",
          title: t("common.failed"),
          description: res.data.error,
        });
    },
  );

  const columns: Column<Receiver>[] = [
    {
      key: "name",
      header: t("common.name"),
      render: (r) => <span className="font-medium">{r.name}</span>,
    },
    {
      key: "type",
      header: "Type",
      render: (r) => <Badge variant="outline">{r.type}</Badge>,
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex justify-end gap-1">
          {canTest && (
            <Button variant="ghost" size="sm" onClick={() => test.mutate(r)}>
              <Send className="h-4 w-4" />
              {t("common.test")}
            </Button>
          )}
          {isAdmin && (
            <Button variant="ghost" size="icon" onClick={() => setDeleting(r)}>
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      {isAdmin && (
        <div className="flex justify-end">
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("common.create")}
          </Button>
        </div>
      )}
      <DataTable
        columns={columns}
        rows={receivers.data?.data ?? []}
        rowKey={(r) => r.id}
        loading={receivers.isLoading}
      />

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Receiver {t("common.create")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <FormField label={t("common.name")} htmlFor="r-name" required>
              <Input id="r-name" value={name} onChange={(e) => setName(e.target.value)} />
            </FormField>
            <FormField label="Type" required>
              <Select value={type} onValueChange={setType}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="slack">slack</SelectItem>
                  <SelectItem value="email">email</SelectItem>
                  <SelectItem value="webhook">webhook</SelectItem>
                  <SelectItem value="pagerduty">pagerduty</SelectItem>
                </SelectContent>
              </Select>
            </FormField>
            <FormField
              label="URL"
              htmlFor="r-url"
              description="Slack webhook / webhook URL (Fernet 암호화 저장)"
            >
              <Input id="r-url" value={url} onChange={(e) => setUrl(e.target.value)} />
            </FormField>
          </div>
          <DialogFooter>
            <Button onClick={() => create.mutate(undefined)} disabled={!name || create.isPending}>
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`${t("common.delete")}: ${deleting?.name ?? ""}`}
        destructive
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
    </div>
  );
}

function PoliciesTab() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const isAdmin = hasRole("admin");
  const policies = usePolicies();
  const receivers = useReceivers();

  const [createOpen, setCreateOpen] = useState(false);
  const [matcherJson, setMatcherJson] = useState('{"severity": "critical"}');
  const [receiverId, setReceiverId] = useState("");
  const [repeatInterval, setRepeatInterval] = useState("4h");

  const receiverName = (id: string) =>
    receivers.data?.data.find((r) => r.id === id)?.name ?? id.slice(0, 8);

  const create = useApiMutation(
    () =>
      api.post("/notification-policies", {
        matcher: JSON.parse(matcherJson || "{}"),
        receiver_id: receiverId,
        group_by: ["alertname"],
        repeat_interval: repeatInterval,
      }),
    ["notification-policies"],
    () => setCreateOpen(false),
  );

  const remove = useApiMutation(
    (p: NotificationPolicy) => api.delete(`/notification-policies/${p.id}`),
    ["notification-policies"],
  );

  const columns: Column<NotificationPolicy>[] = [
    {
      key: "matcher",
      header: "Matcher",
      render: (p) => (
        <code className="text-xs">{JSON.stringify(p.matcher)}</code>
      ),
    },
    {
      key: "receiver",
      header: "Receiver",
      render: (p) => <Badge variant="secondary">{receiverName(p.receiver_id)}</Badge>,
    },
    { key: "repeat", header: "Repeat", render: (p) => p.repeat_interval },
    {
      key: "actions",
      header: "",
      render: (p) =>
        isAdmin ? (
          <Button variant="ghost" size="icon" onClick={() => remove.mutate(p)}>
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-4">
      {isAdmin && (
        <div className="flex justify-end">
          <Button onClick={() => setCreateOpen(true)} disabled={!receivers.data?.data.length}>
            <Plus className="h-4 w-4" />
            {t("common.create")}
          </Button>
        </div>
      )}
      <DataTable
        columns={columns}
        rows={policies.data?.data ?? []}
        rowKey={(p) => p.id}
        loading={policies.isLoading}
      />

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Policy {t("common.create")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <FormField label="Matcher (JSON)" htmlFor="p-matcher">
              <Textarea
                id="p-matcher"
                rows={3}
                value={matcherJson}
                onChange={(e) => setMatcherJson(e.target.value)}
              />
            </FormField>
            <FormField label="Receiver" required>
              <Select value={receiverId} onValueChange={setReceiverId}>
                <SelectTrigger>
                  <SelectValue placeholder="선택..." />
                </SelectTrigger>
                <SelectContent>
                  {(receivers.data?.data ?? []).map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {r.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField label="Repeat interval" htmlFor="p-repeat">
              <Input
                id="p-repeat"
                value={repeatInterval}
                onChange={(e) => setRepeatInterval(e.target.value)}
              />
            </FormField>
          </div>
          <DialogFooter>
            <Button
              onClick={() => create.mutate(undefined)}
              disabled={!receiverId || create.isPending}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SilencesTab() {
  const { t } = useTranslation();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");
  const silences = useSilences();

  const [createOpen, setCreateOpen] = useState(false);
  const [matchersJson, setMatchersJson] = useState('{"alertname": ""}');
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [comment, setComment] = useState("");

  const create = useApiMutation(
    () =>
      api.post("/silences", {
        matchers: JSON.parse(matchersJson || "{}"),
        starts_at: new Date(startsAt).toISOString(),
        ends_at: new Date(endsAt).toISOString(),
        comment,
      }),
    ["silences"],
    () => setCreateOpen(false),
  );

  const remove = useApiMutation(
    (s: Silence) => api.delete(`/silences/${s.id}`),
    ["silences"],
  );

  const columns: Column<Silence>[] = [
    {
      key: "matchers",
      header: "Matchers",
      render: (s) => <code className="text-xs">{JSON.stringify(s.matchers)}</code>,
    },
    { key: "starts", header: "Starts", render: (s) => formatDate(s.starts_at) },
    { key: "ends", header: "Ends", render: (s) => formatDate(s.ends_at) },
    {
      key: "comment",
      header: "Comment",
      render: (s) => <span className="text-muted-foreground">{s.comment}</span>,
    },
    {
      key: "actions",
      header: "",
      render: (s) =>
        canEdit ? (
          <Button variant="ghost" size="icon" onClick={() => remove.mutate(s)}>
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="space-y-4">
      {canEdit && (
        <div className="flex justify-end">
          <Button onClick={() => setCreateOpen(true)}>
            <BellOff className="h-4 w-4" />
            Silence {t("common.create")}
          </Button>
        </div>
      )}
      <DataTable
        columns={columns}
        rows={silences.data?.data ?? []}
        rowKey={(s) => s.id}
        loading={silences.isLoading}
      />

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Silence {t("common.create")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <FormField label="Matchers (JSON)" htmlFor="sl-matchers">
              <Textarea
                id="sl-matchers"
                rows={3}
                value={matchersJson}
                onChange={(e) => setMatchersJson(e.target.value)}
              />
            </FormField>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormField label="Starts at" htmlFor="sl-start" required>
                <Input
                  id="sl-start"
                  type="datetime-local"
                  value={startsAt}
                  onChange={(e) => setStartsAt(e.target.value)}
                />
              </FormField>
              <FormField label="Ends at" htmlFor="sl-end" required>
                <Input
                  id="sl-end"
                  type="datetime-local"
                  value={endsAt}
                  onChange={(e) => setEndsAt(e.target.value)}
                />
              </FormField>
            </div>
            <FormField label="Comment" htmlFor="sl-comment">
              <Input
                id="sl-comment"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
            </FormField>
          </div>
          <DialogFooter>
            <Button
              onClick={() => create.mutate(undefined)}
              disabled={!startsAt || !endsAt || create.isPending}
            >
              {t("common.save")}
            </Button>
          </DialogFooter>
          {create.isError && (
            <p className="text-sm text-destructive">
              {create.error instanceof Error ? create.error.message : t("common.error")}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
