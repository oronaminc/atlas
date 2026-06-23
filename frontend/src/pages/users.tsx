import { useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { History, KeyRound, Plus } from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { api } from "@/api/client";
import { useApiMutation, useAuditLogs, useUsers } from "@/api/queries";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTable, type Column } from "@/components/common/data-table";
import { FormField } from "@/components/common/form-field";
import { Pager } from "@/components/common/pager";
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
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";
import type { User } from "@/types";

const userSchema = z.object({
  email: z.string().email(),
  username: z.string().min(2),
  password: z.string().min(8, "8자 이상"),
  role: z.enum(["admin", "editor", "viewer"]),
});

type UserForm = z.infer<typeof userSchema>;

export function UsersPage() {
  const { t } = useTranslation();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<User | null>(null);
  const [resetting, setResetting] = useState<User | null>(null);
  const [history, setHistory] = useState<User | null>(null);

  const users = useUsers({
    q: search || undefined,
    page: String(page),
    page_size: "20",
  });
  const meta = users.data?.meta;

  const setRole = useApiMutation(
    ({ user, role }: { user: User; role: string }) =>
      api.patch(`/users/${user.id}`, { role }),
    ["users"],
  );

  const toggleActive = useApiMutation(
    (user: User) => api.patch(`/users/${user.id}`, { is_active: !user.is_active }),
    ["users"],
  );

  const remove = useApiMutation(
    (user: User) => api.delete(`/users/${user.id}`),
    ["users"],
    () => setDeleting(null),
  );

  const columns: Column<User>[] = [
    {
      key: "username",
      header: t("common.name"),
      render: (u) => (
        <div>
          <div className="font-medium">{u.username}</div>
          <div className="text-xs text-muted-foreground">{u.email}</div>
        </div>
      ),
    },
    {
      key: "role",
      header: "Role",
      render: (u) => (
        <Select
          value={u.role}
          onValueChange={(role) => setRole.mutate({ user: u, role })}
        >
          <SelectTrigger className="h-8 w-28" onClick={(e) => e.stopPropagation()}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="admin">admin</SelectItem>
            <SelectItem value="editor">editor</SelectItem>
            <SelectItem value="viewer">viewer</SelectItem>
          </SelectContent>
        </Select>
      ),
    },
    {
      key: "provider",
      header: "Auth",
      render: (u) => <Badge variant="outline">{u.auth_provider}</Badge>,
    },
    {
      key: "active",
      header: t("common.enabled"),
      render: (u) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={(e) => {
            e.stopPropagation();
            toggleActive.mutate(u);
          }}
        >
          <Badge variant={u.is_active ? "success" : "secondary"}>
            {u.is_active ? "active" : "inactive"}
          </Badge>
        </Button>
      ),
    },
    {
      key: "last_login",
      header: "Last login",
      render: (u) => (
        <span className="text-muted-foreground">{formatDate(u.last_login_at)}</span>
      ),
    },
    {
      key: "actions",
      header: "",
      render: (u) => (
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            title={t("users.history")}
            onClick={(e) => {
              e.stopPropagation();
              setHistory(u);
            }}
            data-testid="user-history"
          >
            <History className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            title={t("users.resetPassword")}
            onClick={(e) => {
              e.stopPropagation();
              setResetting(u);
            }}
            data-testid="user-reset-pw"
          >
            <KeyRound className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive"
            onClick={(e) => {
              e.stopPropagation();
              setDeleting(u);
            }}
          >
            {t("common.delete")}
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title={t("nav.users")}
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("common.create")}
          </Button>
        }
      />
      <DataTable
        columns={columns}
        rows={users.data?.data ?? []}
        rowKey={(u) => u.id}
        loading={users.isLoading}
        search={{ value: search, onChange: (v) => { setSearch(v); setPage(1); } }}
      />
      <div className="mt-4">
        <Pager
          page={meta?.page ?? page}
          pages={meta?.pages ?? 1}
          total={meta?.total}
          onPage={setPage}
        />
      </div>
      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={`${t("common.delete")}: ${deleting?.username ?? ""}`}
        destructive
        loading={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting)}
      />
      {resetting && (
        <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
      )}
      {history && (
        <UserHistoryDialog user={history} onClose={() => setHistory(null)} />
      )}
    </div>
  );
}

function ResetPasswordDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [password, setPassword] = useState("");

  const reset = useApiMutation(
    () => api.post(`/users/${user.id}/reset-password`, { new_password: password }),
    ["users"],
    () => {
      toast({ title: t("users.resetPasswordDone") });
      onClose();
    },
  );

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {t("users.resetPassword")} — {user.username}
          </DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground">{t("users.resetPasswordHelp")}</p>
        <FormField label={t("auth.newPassword")} htmlFor="reset-pw" required>
          <Input
            id="reset-pw"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            data-testid="reset-pw-input"
          />
        </FormField>
        <DialogFooter>
          <Button
            onClick={() =>
              reset.mutate(undefined, {
                onError: (e) =>
                  toast({
                    variant: "destructive",
                    title: t("common.failed"),
                    description: e instanceof Error ? e.message : String(e),
                  }),
              })
            }
            disabled={password.length < 8 || reset.isPending}
            data-testid="reset-pw-save"
          >
            {t("common.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UserHistoryDialog({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useTranslation();
  const logs = useAuditLogs({ actor_id: user.id, page_size: "25" });
  const rows = logs.data?.data ?? [];

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {t("users.history")} — {user.username}
          </DialogTitle>
        </DialogHeader>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("common.empty")}</p>
        ) : (
          <div className="space-y-1">
            {rows.map((l) => (
              <div
                key={l.id}
                className="flex items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium">{l.action}</span>
                  <Badge variant="outline">{l.resource_type}</Badge>
                  {l.emergency && <Badge variant="destructive">emergency</Badge>}
                </div>
                <span className="text-xs text-muted-foreground">
                  {formatDate(l.created_at)}
                </span>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function CreateUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors },
  } = useForm<UserForm>({
    resolver: zodResolver(userSchema),
    defaultValues: { role: "viewer" },
  });

  const create = useApiMutation(
    (values: UserForm) => api.post("/users", values),
    ["users"],
    () => {
      reset();
      onOpenChange(false);
    },
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("common.create")}</DialogTitle>
        </DialogHeader>
        <form
          id="user-form"
          className="space-y-4"
          onSubmit={handleSubmit((v) => create.mutate(v))}
        >
          <FormField label={t("auth.email")} htmlFor="u-email" error={errors.email} required>
            <Input id="u-email" type="email" {...register("email")} />
          </FormField>
          <FormField label={t("common.name")} htmlFor="u-name" error={errors.username} required>
            <Input id="u-name" {...register("username")} />
          </FormField>
          <FormField
            label={t("auth.password")}
            htmlFor="u-pw"
            error={errors.password}
            required
          >
            <Input id="u-pw" type="password" {...register("password")} />
          </FormField>
          <FormField label="Role" error={errors.role} required>
            <Controller
              control={control}
              name="role"
              render={({ field }) => (
                <Select value={field.value} onValueChange={field.onChange}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="admin">admin</SelectItem>
                    <SelectItem value="editor">editor</SelectItem>
                    <SelectItem value="viewer">viewer</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
          </FormField>
        </form>
        <DialogFooter>
          <Button type="submit" form="user-form" disabled={create.isPending}>
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
  );
}
