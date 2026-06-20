import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { useApiMutation, useServers } from "@/api/queries";
import {
  cmdbCiFromLabels,
  envFromLabels,
  hostnameFromLabels,
  instanceFromLabels,
  serviceFromLabels,
} from "@/lib/server-identity";
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
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import type { Server } from "@/types";

const serverSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  labelsJson: z.string().refine(
    (v) => {
      if (!v.trim()) return true;
      try {
        const parsed = JSON.parse(v);
        return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
      } catch {
        return false;
      }
    },
    { message: "유효한 JSON 객체여야 합니다" },
  ),
});

type ServerForm = z.infer<typeof serverSchema>;

export function ServersPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | undefined>();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Server | null>(null);

  const servers = useServers({ q: search || undefined, cursor, limit: "20" });
  const groups = useQuery({
    queryKey: ["server-groups"],
    queryFn: () => api.get<{ id: string; name: string }[]>("/server-groups"),
  });
  const groupName = (id: string | null) =>
    (id && groups.data?.data.find((g) => g.id === id)?.name) || undefined;

  const columns: Column<Server>[] = [
    {
      key: "host",
      header: t("servers.hostname"),
      render: (s) => {
        const host = hostnameFromLabels(s.labels) ?? s.name;
        const cmdb = s.cmdb_ci ?? cmdbCiFromLabels(s.labels);
        return (
          <div>
            <div className="font-medium">{host}</div>
            {cmdb && <div className="font-mono text-[10px] text-muted-foreground/70">{cmdb}</div>}
          </div>
        );
      },
    },
    {
      key: "ip",
      header: t("servers.ip"),
      render: (s) => (
        <span className="font-mono text-xs text-muted-foreground">
          {instanceFromLabels(s.labels) ?? "—"}
        </span>
      ),
    },
    {
      key: "service",
      header: t("servers.service"),
      render: (s) => <span className="text-sm">{serviceFromLabels(s.labels) ?? "—"}</span>,
    },
    {
      key: "env",
      header: t("servers.environment"),
      render: (s) =>
        envFromLabels(s.labels) ? (
          <Badge variant="outline">{envFromLabels(s.labels)}</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "group",
      header: t("servers.group"),
      render: (s) =>
        groupName(s.server_group_id) ? (
          <Badge variant="secondary">{groupName(s.server_group_id)}</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "labels",
      header: t("rules.labels"),
      render: (s) => (
        <span className="text-xs text-muted-foreground" data-testid="server-label-count">
          {t("servers.labelsCount", { count: Object.keys(s.labels ?? {}).length })}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title={t("nav.servers")}
        actions={
          canEdit && (
            <Button
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4" />
              {t("common.create")}
            </Button>
          )
        }
      />
      <DataTable
        columns={columns}
        rows={servers.data?.data ?? []}
        rowKey={(s) => s.id}
        loading={servers.isLoading}
        search={{ value: search, onChange: (v) => { setSearch(v); setCursor(undefined); } }}
        pagination={{
          hasMore: servers.data?.meta?.has_more ?? false,
          onNext: () => setCursor(servers.data?.meta?.next_cursor ?? undefined),
        }}
        onRowClick={(s) => navigate(`/servers/${s.id}`)}
      />
      <ServerFormDialog open={formOpen} onOpenChange={setFormOpen} server={editing} />
    </div>
  );
}

export function ServerFormDialog({
  open,
  onOpenChange,
  server,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  server: Server | null;
}) {
  const { t } = useTranslation();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ServerForm>({
    resolver: zodResolver(serverSchema),
    defaultValues: {
      name: server?.name ?? "",
      description: server?.description ?? "",
      labelsJson: server ? JSON.stringify(server.labels ?? {}) : "",
    },
  });

  useEffect(() => {
    reset({
      name: server?.name ?? "",
      description: server?.description ?? "",
      labelsJson: server ? JSON.stringify(server.labels ?? {}) : "",
    });
  }, [server, reset, open]);

  const save = useApiMutation(
    (values: ServerForm) => {
      const payload = {
        name: values.name,
        description: values.description || null,
        labels: values.labelsJson.trim() ? JSON.parse(values.labelsJson) : {},
      };
      return server
        ? api.patch(`/servers/${server.id}`, payload)
        : api.post("/servers", payload);
    },
    ["servers"],
    () => onOpenChange(false),
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{server ? t("common.edit") : t("common.create")}</DialogTitle>
        </DialogHeader>
        <form
          id="server-form"
          className="space-y-4"
          onSubmit={handleSubmit((v) => save.mutate(v))}
        >
          <FormField label={t("common.name")} htmlFor="s-name" error={errors.name} required>
            <Input id="s-name" {...register("name")} />
          </FormField>
          <FormField label={t("common.description")} htmlFor="s-desc">
            <Textarea id="s-desc" rows={2} {...register("description")} />
          </FormField>
          <FormField
            label={`${t("rules.labels")} (JSON)`}
            htmlFor="s-labels"
            error={errors.labelsJson}
            description='{"job": "node", "env": "prod"}'
          >
            <Textarea id="s-labels" rows={3} {...register("labelsJson")} />
          </FormField>
        </form>
        <DialogFooter>
          <Button type="submit" form="server-form" disabled={save.isPending}>
            {t("common.save")}
          </Button>
        </DialogFooter>
        {save.isError && (
          <p className="text-sm text-destructive">
            {save.error instanceof Error ? save.error.message : t("common.error")}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
