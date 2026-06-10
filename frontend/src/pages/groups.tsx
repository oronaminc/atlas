import { useState } from "react";
import { Plus, Trash2, UserPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  useApiMutation,
  useGroupMembers,
  useGroups,
  useUsers,
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
import { useAuth } from "@/hooks/use-auth";
import type { Group } from "@/types";

export function GroupsPage() {
  const { t } = useTranslation();
  const { hasRole, user } = useAuth();
  const isAdmin = hasRole("admin");

  const [search, setSearch] = useState("");
  const [cursor, setCursor] = useState<string | undefined>();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [deleting, setDeleting] = useState<Group | null>(null);
  const [membersOf, setMembersOf] = useState<Group | null>(null);

  const groups = useGroups({ q: search || undefined, cursor, limit: "20" });

  const create = useApiMutation(
    () => api.post("/groups", { name, description: description || null }),
    ["groups"],
    () => {
      setCreateOpen(false);
      setName("");
      setDescription("");
    },
  );

  const remove = useApiMutation(
    (group: Group) => api.delete(`/groups/${group.id}`),
    ["groups"],
    () => setDeleting(null),
  );

  const canManage = (group: Group) =>
    isAdmin ||
    (user?.groups ?? []).some(
      (m) => m.group_id === group.id && m.role_in_group === "manager",
    );

  const columns: Column<Group>[] = [
    {
      key: "name",
      header: t("common.name"),
      render: (g) => <span className="font-medium">{g.name}</span>,
    },
    {
      key: "description",
      header: t("common.description"),
      render: (g) => <span className="text-muted-foreground">{g.description ?? "-"}</span>,
    },
    {
      key: "members",
      header: "Members",
      render: (g) => <Badge variant="secondary">{g.member_count ?? 0}</Badge>,
    },
    {
      key: "actions",
      header: "",
      render: (g) => (
        <div className="flex justify-end gap-1">
          {canManage(g) && (
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.stopPropagation();
                setMembersOf(g);
              }}
            >
              <UserPlus className="h-4 w-4" />
            </Button>
          )}
          {isAdmin && (
            <Button
              variant="ghost"
              size="icon"
              onClick={(e) => {
                e.stopPropagation();
                setDeleting(g);
              }}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title={t("nav.groups")}
        actions={
          isAdmin && (
            <Button onClick={() => setCreateOpen(true)}>
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
        search={{ value: search, onChange: (v) => { setSearch(v); setCursor(undefined); } }}
        pagination={{
          hasMore: groups.data?.meta?.has_more ?? false,
          onNext: () => setCursor(groups.data?.meta?.next_cursor ?? undefined),
        }}
      />

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("common.create")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <FormField label={t("common.name")} htmlFor="grp-name" required>
              <Input id="grp-name" value={name} onChange={(e) => setName(e.target.value)} />
            </FormField>
            <FormField label={t("common.description")} htmlFor="grp-desc">
              <Input
                id="grp-desc"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
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

      {membersOf && (
        <MembersDialog group={membersOf} onClose={() => setMembersOf(null)} />
      )}
    </div>
  );
}

function MembersDialog({ group, onClose }: { group: Group; onClose: () => void }) {
  const { t } = useTranslation();
  const members = useGroupMembers(group.id);
  const users = useUsers({ limit: "100" });
  const { hasRole } = useAuth();
  const [selectedUser, setSelectedUser] = useState("");
  const [role, setRole] = useState("member");

  const addMember = useApiMutation(
    () =>
      api.post(`/groups/${group.id}/members`, {
        user_id: selectedUser,
        role_in_group: role,
      }),
    ["groups"],
    () => {
      members.refetch();
      setSelectedUser("");
    },
  );

  const removeMember = useApiMutation(
    (userId: string) => api.delete(`/groups/${group.id}/members/${userId}`),
    ["groups"],
    () => members.refetch(),
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{group.name} — Members</DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          {(members.data?.data ?? []).map((m) => (
            <div
              key={m.user_id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <div>
                <span className="text-sm font-medium">{m.username}</span>
                <span className="ml-2 text-xs text-muted-foreground">{m.email}</span>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={m.role_in_group === "manager" ? "default" : "secondary"}>
                  {m.role_in_group}
                </Badge>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => removeMember.mutate(m.user_id)}
                >
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </div>
            </div>
          ))}
          {(members.data?.data ?? []).length === 0 && (
            <p className="text-sm text-muted-foreground">{t("common.empty")}</p>
          )}
        </div>

        {hasRole("admin") && (
          <div className="flex gap-2">
            <Select value={selectedUser} onValueChange={setSelectedUser}>
              <SelectTrigger className="flex-1">
                <SelectValue placeholder="사용자 선택..." />
              </SelectTrigger>
              <SelectContent>
                {(users.data?.data ?? []).map((u) => (
                  <SelectItem key={u.id} value={u.id}>
                    {u.username} ({u.email})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={role} onValueChange={setRole}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="member">member</SelectItem>
                <SelectItem value="manager">manager</SelectItem>
              </SelectContent>
            </Select>
            <Button
              onClick={() => addMember.mutate(undefined)}
              disabled={!selectedUser || addMember.isPending}
            >
              <UserPlus className="h-4 w-4" />
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
