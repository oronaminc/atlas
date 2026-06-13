/** LLM endpoint config (Feature A) — admin. Self-hosted (vLLM/Ollama/gateway)
 *  is the primary path; external OpenAI only if explicitly set + egress allowed.
 *  api_key is write-only (masked on read). */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/api/client";
import { useApiMutation } from "@/api/queries";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import type { LLMConfig } from "@/types";

export function LLMConfigCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const cfg = useQuery({
    queryKey: ["llm-config"],
    queryFn: () => api.get<LLMConfig>("/llm-config"),
  });

  const [form, setForm] = useState<LLMConfig | null>(null);
  const [apiKey, setApiKey] = useState("");
  useEffect(() => {
    if (cfg.data) setForm(cfg.data.data);
  }, [cfg.data]);

  const save = useApiMutation(
    () =>
      api.patch("/llm-config", {
        enabled: form!.enabled,
        base_url: form!.base_url,
        model: form!.model,
        daily_quota: form!.daily_quota,
        auto_analyze: form!.auto_analyze,
        redact_external_strict: form!.redact_external_strict,
        ...(apiKey ? { api_key: apiKey } : {}),
      }),
    ["llm-config"],
    () => {
      setApiKey("");
      toast({ title: t("common.success") });
    },
  );

  if (!form) return null;
  const keySet = cfg.data?.data.api_key != null;

  return (
    <Card className="max-w-xl" data-testid="llm-config-card">
      <CardHeader>
        <CardTitle className="text-base">{t("llm.title")}</CardTitle>
        <CardDescription>{t("llm.help")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center gap-2">
          <Switch
            id="llm-enabled"
            checked={form.enabled}
            onCheckedChange={(v) => setForm({ ...form, enabled: v })}
          />
          <Label htmlFor="llm-enabled">{t("llm.enabled")}</Label>
        </div>
        <FormField label={t("llm.baseUrl")} htmlFor="llm-base" description={t("llm.baseUrlHelp")}>
          <Input
            id="llm-base"
            value={form.base_url}
            onChange={(e) => setForm({ ...form, base_url: e.target.value })}
            placeholder="http://vllm.internal:8000"
          />
        </FormField>
        <div className="grid grid-cols-2 gap-4">
          <FormField label={t("llm.model")} htmlFor="llm-model">
            <Input
              id="llm-model"
              value={form.model}
              onChange={(e) => setForm({ ...form, model: e.target.value })}
              placeholder="llama-3.1-8b"
            />
          </FormField>
          <FormField label={t("llm.dailyQuota")} htmlFor="llm-quota">
            <Input
              id="llm-quota"
              type="number"
              min={0}
              value={form.daily_quota}
              onChange={(e) => setForm({ ...form, daily_quota: Number(e.target.value) })}
            />
          </FormField>
        </div>
        <FormField
          label={t("llm.apiKey")}
          htmlFor="llm-key"
          description={keySet ? t("llm.keySet") : t("llm.keyUnset")}
        >
          <Input
            id="llm-key"
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={keySet ? "********" : "sk-… / leave blank for none"}
          />
        </FormField>
        <div className="flex items-center gap-2">
          <Switch
            id="llm-auto"
            checked={form.auto_analyze}
            onCheckedChange={(v) => setForm({ ...form, auto_analyze: v })}
          />
          <Label htmlFor="llm-auto">{t("llm.autoAnalyze")}</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="llm-redact"
            checked={form.redact_external_strict}
            onCheckedChange={(v) => setForm({ ...form, redact_external_strict: v })}
          />
          <Label htmlFor="llm-redact">{t("llm.redactStrict")}</Label>
        </div>
        <Button
          onClick={() =>
            save.mutate(undefined, {
              onError: (e) =>
                toast({
                  variant: "destructive",
                  title: t("common.failed"),
                  description: e instanceof Error ? e.message : String(e),
                }),
            })
          }
          disabled={save.isPending}
          data-testid="llm-save"
        >
          {t("common.save")}
        </Button>
      </CardContent>
    </Card>
  );
}
