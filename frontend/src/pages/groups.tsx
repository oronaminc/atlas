import { useEffect, useState } from "react";
import { Pencil, Plus, Tags, Trash2, UserPlus } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import {
  useApiMutation,
  useGroup,
  useGroupMembers,
  useGroups,
  useGroupServiceCodes,
  useLabelNames,
  useUsers,
} from "@/api/queries";
import { Textarea } from "@/components/ui/textarea";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTable, type Column } from "@/components/common/data-table";
import { FormField } from "@/components/common/form-field";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import type { Group, GroupMember } from "@/types";

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
  const [codesOf, setCodesOf] = useState<Group | null>(null);
  const [editing, setEditing] = useState<Group | null>(null);

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
      key: "labels",
      header: t("groups.labels"),
      render: (g) =>
        g.labels && g.labels.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {g.labels.slice(0, 3).map((l) => (
              <Badge key={l} variant="outline">
                {l}
              </Badge>
            ))}
            {g.labels.length > 3 && (
              <Badge variant="outline">+{g.labels.length - 3}</Badge>
            )}
          </div>
        ) : (
          <span className="text-muted-foreground">-</span>
        ),
    },
    {
      key: "members",
      header: t("groups.members"),
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
              title={t("groups.members")}
              onClick={(e) => {
                e.stopPropagation();
                setMembersOf(g);
              }}
            >
              <UserPlus className="h-4 w-4" />
            </Button>
          )}
          {canManage(g) && (
            <Button
              variant="ghost"
              size="icon"
              title={t("common.edit")}
              onClick={(e) => {
                e.stopPropagation();
                setEditing(g);
              }}
              data-testid="edit-group"
            >
              <Pencil className="h-4 w-4" />
            </Button>
          )}
          {isAdmin && (
            <Button
              variant="ghost"
              size="icon"
              title={t("groups.serviceCodes")}
              onClick={(e) => {
                e.stopPropagation();
                setCodesOf(g);
              }}
              data-testid="edit-codes"
            >
              <Tags className="h-4 w-4" />
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
      {codesOf && <CodesDialog group={codesOf} onClose={() => setCodesOf(null)} />}
      {editing && <EditGroupDialog group={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function EditGroupDialog({ group, onClose }: { group: Group; onClose: () => void }) {
  const { t } = useTranslation();
  // The list row may not carry labels; fetch the detail which is guaranteed to.
  const detail = useGroup(group.id);
  const labelNames = useLabelNames();

  const [description, setDescription] = useState(group.description ?? "");
  const [labels, setLabels] = useState<string[]>(group.labels ?? []);
  const [labelFilter, setLabelFilter] = useState("");

  useEffect(() => {
    if (detail.data) {
      setDescription(detail.data.data.description ?? "");
      setLabels(detail.data.data.labels ?? []);
    }
  }, [detail.data]);

  const save = useApiMutation(
    () =>
      api.patch(`/groups/${group.id}`, {
        description: description || null,
        labels,
      }),
    ["groups"],
    onClose,
  );

  const toggleLabel = (name: string) =>
    setLabels((prev) =>
      prev.includes(name) ? prev.filter((l) => l !== name) : [...prev, name],
    );

  const available = (labelNames.data?.data ?? []).filter((n) =>
    n.toLowerCase().includes(labelFilter.toLowerCase()),
  );

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("common.edit")} — {group.name}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <FormField label={t("common.description")} htmlFor="edit-grp-desc">
            <Textarea
              id="edit-grp-desc"
              className="h-20"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              data-testid="group-description"
            />
          </FormField>
          <div className="space-y-2">
            <span className="text-sm font-medium">{t("groups.labels")}</span>
            <p className="text-xs text-muted-foreground">{t("groups.labelsHelp")}</p>
            {labels.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {labels.map((l) => (
                  <Badge key={l} variant="secondary">
                    {l}
                  </Badge>
                ))}
              </div>
            )}
            <Input
              placeholder={t("common.search")}
              value={labelFilter}
              onChange={(e) => setLabelFilter(e.target.value)}
            />
            <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">
              {available.length === 0 && (
                <p className="px-1 text-sm text-muted-foreground">{t("common.empty")}</p>
              )}
              {available.map((name) => (
                <label
                  key={name}
                  className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 text-sm hover:bg-accent/50"
                >
                  <Checkbox
                    checked={labels.includes(name)}
                    onCheckedChange={() => toggleLabel(name)}
                  />
                  {name}
                </label>
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button
            onClick={() => save.mutate(undefined)}
            disabled={save.isPending}
            data-testid="save-group"
          >
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CodesDialog({ group, onClose }: { group: Group; onClose: () => void }) {
  const { t } = useTranslation();
  const codes = useGroupServiceCodes(group.id);
  const [text, setText] = useState("");
  useEffect(() => {
    if (codes.data) setText((codes.data.data.codes ?? []).join("\n"));
  }, [codes.data]);
  const save = useApiMutation(
    () =>
      api.put(`/groups/${group.id}/service-codes`, {
        codes: text.split(/[\s,]+/).filter(Boolean),
      }),
    ["group-service-codes"],
    onClose,
  );
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("groups.serviceCodes")} — {group.name}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">{t("groups.serviceCodesHelp")}</p>
        <Textarea
          className="h-40 font-mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="sub20251126_1040230842"
          data-testid="codes-input"
        />
        <DialogFooter>
          <Button onClick={() => save.mutate(undefined)} disabled={save.isPending} data-testid="save-codes">
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function MembersDialog({ group, onClose }: { group: Group; onClose: () => void }) {
  const { t } = useTranslation();
  const members = useGroupMembers(group.id);
  const users = useUsers({ limit: "100" });
  const { hasRole } = useAuth();
  const [selectedUser, setSelectedUser] = useState("");
  const [role, setRole] = useState("member");
  const [viewing, setViewing] = useState<GroupMember | null>(null);

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
          <DialogTitle>
            {group.name} — {t("groups.members")}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-2">
          {(members.data?.data ?? []).map((m) => (
            <div
              key={m.user_id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <button
                type="button"
                className="flex-1 cursor-pointer text-left hover:underline"
                onClick={() => setViewing(m)}
                data-testid="member-row"
              >
                <span className="text-sm font-medium">{m.username}</span>
                <span className="ml-2 text-xs text-muted-foreground">{m.email}</span>
              </button>
              <div className="flex items-center gap-2">
                <Badge variant={m.role_in_group === "manager" ? "default" : "secondary"}>
                  {m.role_in_group}
                </Badge>
                {hasRole("admin") && (
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => removeMember.mutate(m.user_id)}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" />
                  </Button>
                )}
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

        <Dialog open={!!viewing} onOpenChange={(o) => !o && setViewing(null)}>
          <DialogContent className="max-w-sm">
            <DialogHeader>
              <DialogTitle>{viewing?.username}</DialogTitle>
            </DialogHeader>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">{t("common.name")}</span>
                <span className="font-medium">{viewing?.username}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">{t("auth.email")}</span>
                <span>{viewing?.email}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">{t("groups.roleInGroup")}</span>
                <Badge variant={viewing?.role_in_group === "manager" ? "default" : "secondary"}>
                  {viewing?.role_in_group}
                </Badge>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      </DialogContent>
    </Dialog>
  );
}
