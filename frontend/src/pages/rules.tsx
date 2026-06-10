import { useState } from "react";
import { MoreHorizontal, Plus, Siren } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useRules } from "@/api/queries";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTable, type Column } from "@/components/common/data-table";
import { SeverityBadge } from "@/components/common/status-badge";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { RuleFormDialog } from "@/features/rules/rule-form";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import type { AlertRule } from "@/types";

const ALL = "__all__";

export function RulesPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const [search, setSearch] = useState("");
  const [scopeFilter, setScopeFilter] = useState(ALL);
  const [severityFilter, setSeverityFilter] = useState(ALL);
  const [enabledFilter, setEnabledFilter] = useState(ALL);
  const [cursor, setCursor] = useState<string | undefined>();

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AlertRule | null>(null);
  const [deleting, setDeleting] = useState<AlertRule | null>(null);
  const [emergency, setEmergency] = useState<AlertRule | null>(null);
  const [emergencyReason, setEmergencyReason] = useState("");

  const rules = useRules({
    q: search || undefined,
    scope_type: scopeFilter === ALL ? undefined : scopeFilter,
    severity: severityFilter === ALL ? undefined : severityFilter,
    enabled: enabledFilter === ALL ? undefined : enabledFilter,
    cursor,
    limit: "20",
  });

  const toggle = useApiMutation(
    (rule: AlertRule) =>
      api.post(`/rules/${rule.id}/${rule.enabled ? "disable" : "enable"}`),
    ["rules"],
  );

  const remove = useApiMutation(
    (rule: AlertRule) => api.delete(`/rules/${rule.id}`),
    ["rules"],
    () => setDeleting(null),
  );

  const emergencyApply = useApiMutation(
    ({ rule, reason }: { rule: AlertRule; reason: string }) =>
      api.post("/rules/emergency-apply", { rule_id: rule.id, reason }),
    ["rules", "audit-logs"],
    () => {
      toast({ title: t("rules.emergencyApply"), description: t("common.success") });
      setEmergency(null);
      setEmergencyReason("");
    },
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
      key: "datasource",
      header: t("rules.datasource"),
      render: (r) => <span className="text-muted-foreground">{r.datasource}</span>,
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
    {
      key: "actions",
      header: "",
      className: "w-12",
      render: (r) =>
        canEdit ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="icon"
                onClick={(e) => e.stopPropagation()}
              >
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              onClick={(e) => e.stopPropagation()}
            >
              <DropdownMenuItem
                onClick={() => {
                  setEditing(r);
                  setFormOpen(true);
                }}
              >
                {t("common.edit")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => toggle.mutate(r)}>
                {r.enabled ? t("common.disabled") : t("common.enabled")}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-amber-600"
                onClick={() => setEmergency(r)}
              >
                <Siren className="h-4 w-4" />
                {t("rules.emergencyApply")}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive"
                onClick={() => setDeleting(r)}
              >
                {t("common.delete")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null,
    },
  ];

  return (
    <div>
      <PageHeader
        title={t("rules.title")}
        actions={
          canEdit && (
            <Button
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
            >
              <Plus className="h-4 w-4" />
              {t("rules.create")}
            </Button>
          )
        }
      />

      <DataTable
        columns={columns}
        rows={rules.data?.data ?? []}
        rowKey={(r) => r.id}
        loading={rules.isLoading}
        search={{
          value: search,
          onChange: (v) => {
            setSearch(v);
            setCursor(undefined);
          },
        }}
        filters={
          <div className="flex flex-wrap gap-2">
            <Select value={scopeFilter} onValueChange={(v) => { setScopeFilter(v); setCursor(undefined); }}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>scope: all</SelectItem>
                <SelectItem value="global">global</SelectItem>
                <SelectItem value="server">server</SelectItem>
                <SelectItem value="user">user</SelectItem>
                <SelectItem value="group">group</SelectItem>
              </SelectContent>
            </Select>
            <Select value={severityFilter} onValueChange={(v) => { setSeverityFilter(v); setCursor(undefined); }}>
              <SelectTrigger className="w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>severity: all</SelectItem>
                <SelectItem value="critical">critical</SelectItem>
                <SelectItem value="warning">warning</SelectItem>
                <SelectItem value="info">info</SelectItem>
              </SelectContent>
            </Select>
            <Select value={enabledFilter} onValueChange={(v) => { setEnabledFilter(v); setCursor(undefined); }}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>enabled: all</SelectItem>
                <SelectItem value="true">on</SelectItem>
                <SelectItem value="false">off</SelectItem>
              </SelectContent>
            </Select>
          </div>
        }
        pagination={{
          hasMore: rules.data?.meta?.has_more ?? false,
          onNext: () => setCursor(rules.data?.meta?.next_cursor ?? undefined),
        }}
        onRowClick={
          canEdit
            ? (r) => {
                setEditing(r);
                setFormOpen(true);
              }
            : undefined
        }
      />

      <RuleFormDialog open={formOpen} onOpenChange={setFormOpen} rule={editing} />

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`${t("common.delete")}: ${deleting?.name ?? ""}`}
        destructive
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />

      <ConfirmDialog
        open={!!emergency}
        onOpenChange={(open) => {
          if (!open) {
            setEmergency(null);
            setEmergencyReason("");
          }
        }}
        title={`${t("rules.emergencyApply")}: ${emergency?.name ?? ""}`}
        description={t("rules.emergencyConfirm")}
        confirmLabel={t("rules.emergencyApply")}
        destructive
        loading={emergencyApply.isPending}
        onConfirm={() => {
          if (!emergency) return;
          if (!emergencyReason.trim()) {
            toast({
              variant: "destructive",
              title: t("rules.emergencyReason"),
            });
            return;
          }
          emergencyApply.mutate({ rule: emergency, reason: emergencyReason });
        }}
      >
        <Textarea
          value={emergencyReason}
          onChange={(e) => setEmergencyReason(e.target.value)}
          placeholder={t("rules.emergencyReason")}
          rows={3}
        />
      </ConfirmDialog>
    </div>
  );
}
