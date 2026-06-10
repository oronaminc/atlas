import { useEffect, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { MoreHorizontal, Plus, RefreshCw } from "lucide-react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { api } from "@/api/client";
import { useApiMutation, useRuleGroups, useRules } from "@/api/queries";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTable, type Column } from "@/components/common/data-table";
import { FormField } from "@/components/common/form-field";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import type { RuleGroup } from "@/types";

const groupSchema = z.object({
  name: z.string().min(1),
  namespace: z.string().min(1),
  interval: z.string().regex(/^\d+(ms|s|m|h|d|w|y)$/, "예: 1m"),
});

type GroupForm = z.infer<typeof groupSchema>;

export function RuleGroupsPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const [cursor, setCursor] = useState<string | undefined>();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<RuleGroup | null>(null);
  const [deleting, setDeleting] = useState<RuleGroup | null>(null);

  const groups = useRuleGroups({ cursor, limit: "20" });

  const syncNow = useApiMutation(
    (group: RuleGroup) => api.post(`/rule-groups/${group.id}/sync`),
    ["rule-groups", "sync-state"],
    () => toast({ title: t("sync.syncNow"), description: t("common.success") }),
  );

  const remove = useApiMutation(
    (group: RuleGroup) => api.delete(`/rule-groups/${group.id}`),
    ["rule-groups"],
    () => setDeleting(null),
  );

  const columns: Column<RuleGroup>[] = [
    {
      key: "name",
      header: t("common.name"),
      render: (g) => <span className="font-medium">{g.name}</span>,
    },
    { key: "namespace", header: "Namespace", render: (g) => g.namespace },
    { key: "interval", header: "Interval", render: (g) => g.interval },
    { key: "rules", header: "Rules", render: (g) => g.rule_count ?? 0 },
    {
      key: "actions",
      header: "",
      className: "w-12",
      render: (g) =>
        canEdit ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" onClick={(e) => e.stopPropagation()}>
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
              <DropdownMenuItem
                onClick={() => {
                  setEditing(g);
                  setFormOpen(true);
                }}
              >
                {t("common.edit")}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => syncNow.mutate(g)}>
                <RefreshCw className="h-4 w-4" />
                {t("sync.syncNow")}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="text-destructive"
                onClick={() => setDeleting(g)}
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
        title={t("nav.ruleGroups")}
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
        rows={groups.data?.data ?? []}
        rowKey={(g) => g.id}
        loading={groups.isLoading}
        pagination={{
          hasMore: groups.data?.meta?.has_more ?? false,
          onNext: () => setCursor(groups.data?.meta?.next_cursor ?? undefined),
        }}
      />
      <RuleGroupFormDialog open={formOpen} onOpenChange={setFormOpen} group={editing} />
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

function RuleGroupFormDialog({
  open,
  onOpenChange,
  group,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  group: RuleGroup | null;
}) {
  const { t } = useTranslation();
  const rules = useRules({ limit: "100" });
  const [selectedRules, setSelectedRules] = useState<string[]>([]);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<GroupForm>({ resolver: zodResolver(groupSchema) });

  useEffect(() => {
    reset({
      name: group?.name ?? "",
      namespace: group?.namespace ?? "atlas",
      interval: group?.interval ?? "1m",
    });
    setSelectedRules(group?.rules?.map((r) => r.id) ?? []);
  }, [group, reset, open]);

  // When editing, the list endpoint doesn't include rules; fetch the detail.
  useEffect(() => {
    if (!group || !open) return;
    api
      .get<RuleGroup>(`/rule-groups/${group.id}`)
      .then((res) => setSelectedRules(res.data.rules?.map((r) => r.id) ?? []))
      .catch(() => undefined);
  }, [group, open]);

  const save = useApiMutation(
    (values: GroupForm) => {
      const payload = { ...values, rule_ids: selectedRules };
      return group
        ? api.patch(`/rule-groups/${group.id}`, payload)
        : api.post("/rule-groups", payload);
    },
    ["rule-groups"],
    () => onOpenChange(false),
  );

  const toggleRule = (id: string, checked: boolean) => {
    setSelectedRules((prev) =>
      checked ? [...prev, id] : prev.filter((r) => r !== id),
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{group ? t("common.edit") : t("common.create")}</DialogTitle>
        </DialogHeader>
        <form
          id="rule-group-form"
          className="space-y-4"
          onSubmit={handleSubmit((v) => save.mutate(v))}
        >
          <FormField label={t("common.name")} htmlFor="g-name" error={errors.name} required>
            <Input id="g-name" {...register("name")} />
          </FormField>
          <FormField label="Namespace" htmlFor="g-ns" error={errors.namespace} required>
            <Input id="g-ns" {...register("namespace")} />
          </FormField>
          <FormField label="Interval" htmlFor="g-interval" error={errors.interval} required>
            <Input id="g-interval" placeholder="1m" {...register("interval")} />
          </FormField>

          <FormField label={t("nav.rules")}>
            <div className="max-h-48 space-y-2 overflow-y-auto rounded-md border p-3">
              {(rules.data?.data ?? []).map((rule) => (
                <label key={rule.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={selectedRules.includes(rule.id)}
                    onCheckedChange={(checked) => toggleRule(rule.id, checked === true)}
                  />
                  <span className="font-medium">{rule.name}</span>
                  <span className="truncate font-mono text-xs text-muted-foreground">
                    {rule.expr}
                  </span>
                </label>
              ))}
              {(rules.data?.data ?? []).length === 0 && (
                <p className="text-sm text-muted-foreground">{t("common.empty")}</p>
              )}
            </div>
          </FormField>
        </form>
        <DialogFooter>
          <Button type="submit" form="rule-group-form" disabled={save.isPending}>
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
