import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useServer, useServerRules } from "@/api/queries";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTable, type Column } from "@/components/common/data-table";
import { LoadingSpinner } from "@/components/common/loading-spinner";
import { SeverityBadge } from "@/components/common/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ServerFormDialog } from "@/pages/servers";
import { useAuth } from "@/hooks/use-auth";
import type { AlertRule } from "@/types";

export function ServerDetailPage() {
  const { id = "" } = useParams();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const server = useServer(id);
  const rules = useServerRules(id);
  const [editOpen, setEditOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const remove = useApiMutation(
    () => api.delete(`/servers/${id}`),
    ["servers"],
    () => navigate("/servers"),
  );

  const columns: Column<AlertRule>[] = [
    {
      key: "name",
      header: t("common.name"),
      render: (r) => (
        <div>
          <div className="font-medium">{r.name}</div>
          <div className="max-w-md truncate font-mono text-xs text-muted-foreground">
            {r.expr}
          </div>
        </div>
      ),
    },
    {
      key: "scope",
      header: t("rules.scope"),
      render: (r) => <Badge variant="outline">{r.scope_type}</Badge>,
    },
    {
      key: "severity",
      header: t("rules.severity"),
      render: (r) => <SeverityBadge severity={r.severity} />,
    },
    {
      key: "enabled",
      header: t("common.enabled"),
      render: (r) => (
        <Badge variant={r.enabled ? "success" : "secondary"}>
          {r.enabled ? "on" : "off"}
        </Badge>
      ),
    },
  ];

  if (server.isLoading) return <LoadingSpinner />;
  const data = server.data?.data;
  if (!data) return null;

  return (
    <div>
      <Button variant="ghost" size="sm" className="mb-2" onClick={() => navigate("/servers")}>
        <ArrowLeft className="h-4 w-4" />
        {t("nav.servers")}
      </Button>
      <PageHeader
        title={data.name}
        description={data.description ?? undefined}
        actions={
          canEdit && (
            <>
              <Button variant="outline" onClick={() => setEditOpen(true)}>
                <Pencil className="h-4 w-4" />
                {t("common.edit")}
              </Button>
              <Button variant="destructive" onClick={() => setDeleteOpen(true)}>
                <Trash2 className="h-4 w-4" />
                {t("common.delete")}
              </Button>
            </>
          )
        }
      />

      <div className="mb-6 flex flex-wrap gap-1">
        {Object.entries(data.labels ?? {}).map(([k, v]) => (
          <Badge key={k} variant="secondary">
            {k}={v}
          </Badge>
        ))}
      </div>

      <h2 className="mb-3 text-lg font-semibold">{t("nav.rules")}</h2>
      <DataTable
        columns={columns}
        rows={rules.data?.data ?? []}
        rowKey={(r) => r.id}
        loading={rules.isLoading}
      />

      <ServerFormDialog open={editOpen} onOpenChange={setEditOpen} server={data} />
      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`${t("common.delete")}: ${data.name}`}
        destructive
        loading={remove.isPending}
        onConfirm={() => remove.mutate(undefined)}
      />
    </div>
  );
}
