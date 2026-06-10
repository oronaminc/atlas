import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { zodResolver } from "@hookform/resolvers/zod";
import { Activity, KeyRound } from "lucide-react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { FormField } from "@/components/common/form-field";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/hooks/use-auth";

const loginSchema = z.object({
  email: z.string().email("올바른 이메일을 입력하세요"),
  password: z.string().min(1, "비밀번호를 입력하세요"),
});

type LoginForm = z.infer<typeof loginSchema>;

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [submitting, setSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (values: LoginForm) => {
    setSubmitting(true);
    try {
      await login(values.email, values.password);
      navigate("/");
    } catch (e) {
      toast({
        variant: "destructive",
        title: t("auth.loginFailed"),
        description: e instanceof Error ? e.message : undefined,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="items-center text-center">
          <div className="mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
            <Activity className="h-6 w-6 text-primary" />
          </div>
          <CardTitle>Atlas</CardTitle>
          <CardDescription>Observability Alert Management</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            variant="outline"
            className="w-full"
            onClick={() => {
              window.location.href = `${API_BASE}/auth/oidc/login`;
            }}
          >
            <KeyRound className="h-4 w-4" />
            {t("auth.loginWithSSO")}
          </Button>

          <div className="flex items-center gap-3">
            <Separator className="flex-1" />
            <span className="text-xs uppercase text-muted-foreground">
              {t("auth.or")}
            </span>
            <Separator className="flex-1" />
          </div>

          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              label={t("auth.email")}
              htmlFor="email"
              error={errors.email}
            >
              <Input
                id="email"
                type="email"
                autoComplete="email"
                {...register("email")}
              />
            </FormField>
            <FormField
              label={t("auth.password")}
              htmlFor="password"
              error={errors.password}
            >
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                {...register("password")}
              />
            </FormField>
            <Button type="submit" className="w-full" disabled={submitting}>
              {t("auth.login")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
