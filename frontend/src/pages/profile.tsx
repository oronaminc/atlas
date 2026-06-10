import { zodResolver } from "@hookform/resolvers/zod";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { api } from "@/api/client";
import { FormField } from "@/components/common/form-field";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "현재 비밀번호를 입력하세요"),
    new_password: z.string().min(8, "8자 이상이어야 합니다"),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, {
    message: "비밀번호가 일치하지 않습니다",
    path: ["confirm"],
  });

type PasswordForm = z.infer<typeof passwordSchema>;

export function ProfilePage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const { toast } = useToast();

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<PasswordForm>({ resolver: zodResolver(passwordSchema) });

  const onSubmit = async (values: PasswordForm) => {
    try {
      await api.post("/auth/me/password", {
        current_password: values.current_password,
        new_password: values.new_password,
      });
      toast({ title: t("common.success") });
      reset();
    } catch (e) {
      toast({
        variant: "destructive",
        title: t("common.failed"),
        description: e instanceof Error ? e.message : undefined,
      });
    }
  };

  return (
    <div>
      <PageHeader title={t("nav.profile")} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{user?.username}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">{t("auth.email")}</span>
              <span>{user?.email}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Role</span>
              <Badge>{user?.role}</Badge>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Auth</span>
              <Badge variant="outline">{user?.auth_provider}</Badge>
            </div>
            <div>
              <span className="text-muted-foreground">Groups</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {(user?.groups ?? []).map((g) => (
                  <Badge key={g.group_id} variant="secondary">
                    {g.group_name}
                    {g.role_in_group === "manager" && " (manager)"}
                  </Badge>
                ))}
                {(user?.groups ?? []).length === 0 && (
                  <span className="text-xs text-muted-foreground">-</span>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {user?.auth_provider === "local" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{t("auth.changePassword")}</CardTitle>
            </CardHeader>
            <CardContent>
              <form className="space-y-4" onSubmit={handleSubmit(onSubmit)}>
                <FormField
                  label={t("auth.currentPassword")}
                  htmlFor="cur-pw"
                  error={errors.current_password}
                  required
                >
                  <Input id="cur-pw" type="password" {...register("current_password")} />
                </FormField>
                <FormField
                  label={t("auth.newPassword")}
                  htmlFor="new-pw"
                  error={errors.new_password}
                  required
                >
                  <Input id="new-pw" type="password" {...register("new_password")} />
                </FormField>
                <FormField
                  label={`${t("auth.newPassword")} (확인)`}
                  htmlFor="confirm-pw"
                  error={errors.confirm}
                  required
                >
                  <Input id="confirm-pw" type="password" {...register("confirm")} />
                </FormField>
                <Button type="submit" disabled={isSubmitting}>
                  {t("common.save")}
                </Button>
              </form>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
