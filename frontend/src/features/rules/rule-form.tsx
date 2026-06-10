import { useEffect, useState } from "react";
import Editor from "@monaco-editor/react";
import { zodResolver } from "@hookform/resolvers/zod";
import { Controller, useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { api } from "@/api/client";
import { useGroups, useServers, useApiMutation } from "@/api/queries";
import { FormField } from "@/components/common/form-field";
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
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";
import { useTheme } from "@/components/theme-provider";
import { useToast } from "@/hooks/use-toast";
import type { AlertRule } from "@/types";

const ruleSchema = z.object({
  name: z.string().min(1, "이름을 입력하세요"),
  description: z.string().optional(),
  scope_type: z.enum(["global", "server", "user", "group"]),
  scope_ref_id: z.string().optional(),
  expr: z.string().min(1, "표현식을 입력하세요"),
  for_duration: z
    .string()
    .regex(/^\d+(ms|s|m|h|d|w|y)$/, "예: 30s, 5m, 1h"),
  severity: z.enum(["critical", "warning", "info"]),
  datasource: z.enum(["metrics", "logs"]),
  enabled: z.boolean(),
  labelsJson: z.string().refine(isJsonObject, "유효한 JSON 객체여야 합니다"),
  annotationsJson: z.string().refine(isJsonObject, "유효한 JSON 객체여야 합니다"),
});

function isJsonObject(v: string): boolean {
  if (!v.trim()) return true;
  try {
    const parsed = JSON.parse(v);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
  } catch {
    return false;
  }
}

type RuleForm = z.infer<typeof ruleSchema>;

function toPayload(values: RuleForm) {
  return {
    name: values.name,
    description: values.description || null,
    scope_type: values.scope_type,
    scope_ref_id:
      values.scope_type === "global" ? null : values.scope_ref_id || null,
    expr: values.expr,
    for_duration: values.for_duration,
    severity: values.severity,
    datasource: values.datasource,
    enabled: values.enabled,
    labels: values.labelsJson.trim() ? JSON.parse(values.labelsJson) : {},
    annotations: values.annotationsJson.trim()
      ? JSON.parse(values.annotationsJson)
      : {},
  };
}

export function RuleFormDialog({
  open,
  onOpenChange,
  rule,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  rule: AlertRule | null;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { user } = useAuth();
  const { theme } = useTheme();
  const servers = useServers({ limit: "100" });
  const groups = useGroups({ limit: "100" });
  const [previewResult, setPreviewResult] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    getValues,
    formState: { errors },
  } = useForm<RuleForm>({
    resolver: zodResolver(ruleSchema),
    defaultValues: defaultsFrom(rule),
  });

  useEffect(() => {
    reset(defaultsFrom(rule));
    setPreviewResult(null);
  }, [rule, reset, open]);

  const scopeType = watch("scope_type");
  const datasource = watch("datasource");

  const save = useApiMutation(
    (values: RuleForm) =>
      rule
        ? api.patch(`/rules/${rule.id}`, toPayload(values))
        : api.post("/rules", toPayload(values)),
    ["rules", "servers"],
    () => {
      toast({ title: t("common.success") });
      onOpenChange(false);
    },
  );

  const handleValidate = async () => {
    // Validation needs a persisted rule; for new rules we do a quick client check.
    if (!rule) {
      toast({ title: t("rules.validateOk"), description: "저장 후 서버 검증이 수행됩니다." });
      return;
    }
    try {
      const res = await api.post<{ valid: boolean; errors: string[] }>(
        `/rules/${rule.id}/validate`,
      );
      if (res.data.valid) {
        toast({ title: t("rules.validateOk") });
      } else {
        toast({
          variant: "destructive",
          title: t("common.failed"),
          description: res.data.errors.join("; "),
        });
      }
    } catch (e) {
      toast({
        variant: "destructive",
        title: t("common.error"),
        description: e instanceof Error ? e.message : undefined,
      });
    }
  };

  const handlePreview = async () => {
    if (!rule) return;
    try {
      const res = await api.post<{ success: boolean; result: unknown[]; error?: string }>(
        `/rules/${rule.id}/test`,
      );
      setPreviewResult(
        res.data.success
          ? JSON.stringify(res.data.result, null, 2)
          : `Error: ${res.data.error}`,
      );
    } catch (e) {
      setPreviewResult(e instanceof Error ? e.message : "preview failed");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>
            {rule ? t("common.edit") : t("rules.create")}
          </DialogTitle>
        </DialogHeader>

        <form
          id="rule-form"
          onSubmit={handleSubmit((v) => save.mutate(v))}
          className="space-y-4"
        >
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label={t("common.name")} htmlFor="name" error={errors.name} required>
              <Input id="name" {...register("name")} />
            </FormField>
            <FormField
              label={t("rules.forDuration")}
              htmlFor="for_duration"
              error={errors.for_duration}
              required
            >
              <Input id="for_duration" placeholder="5m" {...register("for_duration")} />
            </FormField>
          </div>

          <FormField label={t("common.description")} htmlFor="description">
            <Textarea id="description" rows={2} {...register("description")} />
          </FormField>

          <div className="grid gap-4 sm:grid-cols-3">
            <FormField label={t("rules.scope")} error={errors.scope_type} required>
              <Controller
                control={control}
                name="scope_type"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="global">global</SelectItem>
                      <SelectItem value="server">server</SelectItem>
                      <SelectItem value="user">user</SelectItem>
                      <SelectItem value="group">group</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </FormField>

            <FormField label={t("rules.severity")} error={errors.severity} required>
              <Controller
                control={control}
                name="severity"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="critical">critical</SelectItem>
                      <SelectItem value="warning">warning</SelectItem>
                      <SelectItem value="info">info</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </FormField>

            <FormField label={t("rules.datasource")} error={errors.datasource} required>
              <Controller
                control={control}
                name="datasource"
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="metrics">metrics (PromQL)</SelectItem>
                      <SelectItem value="logs">logs (LogQL)</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </FormField>
          </div>

          {scopeType !== "global" && (
            <FormField
              label={`${t("rules.scope")} — ${scopeType}`}
              error={errors.scope_ref_id}
            >
              <Controller
                control={control}
                name="scope_ref_id"
                render={({ field }) =>
                  scopeType === "user" ? (
                    <Input value={user?.id ?? ""} readOnly />
                  ) : (
                    <Select value={field.value ?? ""} onValueChange={field.onChange}>
                      <SelectTrigger>
                        <SelectValue placeholder="선택..." />
                      </SelectTrigger>
                      <SelectContent>
                        {(scopeType === "server"
                          ? (servers.data?.data ?? []).map((s) => ({ id: s.id, name: s.name }))
                          : (groups.data?.data ?? []).map((g) => ({ id: g.id, name: g.name }))
                        ).map((opt) => (
                          <SelectItem key={opt.id} value={opt.id}>
                            {opt.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )
                }
              />
            </FormField>
          )}

          <FormField
            label={`${t("rules.expression")} (${datasource === "metrics" ? "PromQL" : "LogQL"})`}
            error={errors.expr}
            required
          >
            <div className="overflow-hidden rounded-md border">
              <Controller
                control={control}
                name="expr"
                render={({ field }) => (
                  <Editor
                    height="120px"
                    language="plaintext"
                    theme={theme === "dark" ? "vs-dark" : "light"}
                    value={field.value}
                    onChange={(v) => field.onChange(v ?? "")}
                    options={{
                      minimap: { enabled: false },
                      lineNumbers: "off",
                      fontSize: 13,
                      scrollBeyondLastLine: false,
                      wordWrap: "on",
                    }}
                  />
                )}
              />
            </div>
          </FormField>

          <div className="grid gap-4 sm:grid-cols-2">
            <FormField
              label={`${t("rules.labels")} (JSON)`}
              error={errors.labelsJson}
            >
              <Textarea rows={3} placeholder='{"team": "infra"}' {...register("labelsJson")} />
            </FormField>
            <FormField
              label={`${t("rules.annotations")} (JSON)`}
              error={errors.annotationsJson}
            >
              <Textarea
                rows={3}
                placeholder='{"summary": "..."}'
                {...register("annotationsJson")}
              />
            </FormField>
          </div>

          <div className="flex items-center gap-2">
            <Controller
              control={control}
              name="enabled"
              render={({ field }) => (
                <Switch checked={field.value} onCheckedChange={field.onChange} />
              )}
            />
            <span className="text-sm">{t("common.enabled")}</span>
          </div>

          {previewResult !== null && (
            <pre className="max-h-48 overflow-auto rounded-md bg-muted p-3 text-xs">
              {previewResult}
            </pre>
          )}
        </form>

        <DialogFooter className="gap-2">
          {rule && (
            <>
              <Button type="button" variant="outline" onClick={handleValidate}>
                {t("common.validate")}
              </Button>
              <Button type="button" variant="outline" onClick={handlePreview}>
                {t("rules.preview")}
              </Button>
            </>
          )}
          <Button type="submit" form="rule-form" disabled={save.isPending}>
            {t("common.save")}
          </Button>
        </DialogFooter>
        {save.isError && (
          <p className="text-sm text-destructive">
            {save.error instanceof Error ? save.error.message : t("common.error")}
          </p>
        )}
        <span className="sr-only">{getValues("name")}</span>
      </DialogContent>
    </Dialog>
  );
}

function defaultsFrom(rule: AlertRule | null): RuleForm {
  return {
    name: rule?.name ?? "",
    description: rule?.description ?? "",
    scope_type: rule?.scope_type ?? "global",
    scope_ref_id: rule?.scope_ref_id ?? "",
    expr: rule?.expr ?? "",
    for_duration: rule?.for_duration ?? "5m",
    severity: rule?.severity ?? "warning",
    datasource: rule?.datasource ?? "metrics",
    enabled: rule?.enabled ?? true,
    labelsJson: rule ? JSON.stringify(rule.labels ?? {}, null, 0) : "",
    annotationsJson: rule ? JSON.stringify(rule.annotations ?? {}, null, 0) : "",
  };
}
