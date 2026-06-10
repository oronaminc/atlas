import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { api } from "@/api/client";
import { useApiMutation, useServers } from "@/api/queries";
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

  const columns: Column<Server>[] = [
    {
      key: "name",
      header: t("common.name"),
      render: (s) => <span className="font-medium">{s.name}</span>,
    },
    {
      key: "labels",
      header: t("rules.labels"),
      render: (s) => (
        <div className="flex flex-wrap gap-1">
          {Object.entries(s.labels ?? {}).map(([k, v]) => (
            <Badge key={k} variant="secondary">
              {k}={v}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      key: "description",
      header: t("common.description"),
      render: (s) => <span className="text-muted-foreground">{s.description ?? "-"}</span>,
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
