/** Mimir label-query lookback window (hours). Admin-only (/settings is gated).
 *  Bounds the label-autocomplete proxy so a stale Mimir bucket index can't 422
 *  the whole query. DB-authoritative; default 1h. */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation } from "@/api/queries";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/hooks/use-toast";

interface Cfg {
  label_query_lookback_hours: number;
}

export function MimirQueryCard() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const config = useQuery({
    queryKey: ["mimir-query-config"],
    queryFn: () => api.get<Cfg>("/mimir-query-config"),
  });

  const [hours, setHours] = useState<number | null>(null);
  useEffect(() => {
    if (config.data) setHours(config.data.data.label_query_lookback_hours);
  }, [config.data]);

  const save = useApiMutation(
    () => api.patch<Cfg>("/mimir-query-config", { label_query_lookback_hours: hours }),
    ["mimir-query-config"],
    () => toast({ title: t("common.success") }),
  );

  if (hours == null) return null;

  return (
    <Card className="max-w-xl" data-testid="mimir-query-card">
      <CardHeader>
        <CardTitle className="text-base">{t("mimirQuery.title")}</CardTitle>
        <CardDescription>{t("mimirQuery.help")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <Label htmlFor="mq-lookback">{t("mimirQuery.lookbackHours")}</Label>
          <Input
            id="mq-lookback"
            type="number"
            min={1}
            max={720}
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
          />
        </div>
        <Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>
          {t("common.save")}
        </Button>
      </CardContent>
    </Card>
  );
}
