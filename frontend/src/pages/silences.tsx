/** Silences (Mimir Alertmanager). View open to all; create/expire editor+.
 *  The user picks a service or a server + a window + description — atlas builds
 *  the label matcher (cmdb_service_l2_code / cmdb_ci). No query/matcher input.
 *  A silence blocks the alert Mimir-side; it coexists with the atlas-side
 *  per-incident notification toggle. */

import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation, useLabelValues, useSilences } from "@/api/queries";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";
import { formatDate } from "@/lib/utils";

type Kind = "service" | "server";
const LABEL: Record<Kind, string> = { service: "cmdb_service_l2_code", server: "cmdb_ci" };

export function SilencesPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");
  const silences = useSilences();

  const fail = (e: unknown) =>
    toast({
      variant: "destructive",
      title: t("common.failed"),
      description: e instanceof Error ? e.message : String(e),
    });

  const del = useApiMutation((id: string) => api.delete(`/silences/${id}`), ["silences"]);

  return (
    <div className="space-y-4">
      <PageHeader title={t("nav.silence")} description={t("silence.description")} />

      {canEdit && <SilenceForm onError={fail} />}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("silence.target")}</TableHead>
            <TableHead>{t("silence.state")}</TableHead>
            <TableHead>{t("silence.starts")}</TableHead>
            <TableHead>{t("silence.ends")}</TableHead>
            <TableHead>{t("silence.comment")}</TableHead>
            <TableHead>{t("silence.createdBy")}</TableHead>
            {canEdit && <TableHead />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {(silences.data?.data ?? []).map((s) => (
            <TableRow key={s.silence_id}>
              <TableCell className="font-mono text-xs">
                {s.matchers.map((m) => `${m.name}=${m.value}`).join(", ")}
              </TableCell>
              <TableCell>
                <Badge variant={s.state === "active" ? "warning" : "secondary"}>
                  {s.state ?? "—"}
                </Badge>
              </TableCell>
              <TableCell className="text-muted-foreground">
                {s.starts_at ? formatDate(s.starts_at) : "—"}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {s.ends_at ? formatDate(s.ends_at) : "—"}
              </TableCell>
              <TableCell>{s.comment ?? "—"}</TableCell>
              <TableCell className="text-muted-foreground">{s.created_by_label ?? "—"}</TableCell>
              {canEdit && (
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => del.mutate(s.silence_id, { onError: fail })}
                  >
                    {t("silence.expire")}
                  </Button>
                </TableCell>
              )}
            </TableRow>
          ))}
          {silences.data?.data.length === 0 && (
            <TableRow>
              <TableCell colSpan={canEdit ? 7 : 6} className="text-center text-muted-foreground">
                {t("silence.none")}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}

function SilenceForm({ onError }: { onError: (e: unknown) => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const [kind, setKind] = useState<Kind>("service");
  const [value, setValue] = useState("");
  const [starts, setStarts] = useState("");
  const [ends, setEnds] = useState("");
  const [comment, setComment] = useState("");
  const choices = useLabelValues(LABEL[kind]);

  const create = useApiMutation(
    (body: Record<string, string>) => api.post("/silences", body),
    ["silences"],
  );

  const submit = () => {
    if (!value || !starts || !ends) return;
    create.mutate(
      {
        target_kind: kind,
        target_value: value,
        starts_at: new Date(starts).toISOString(),
        ends_at: new Date(ends).toISOString(),
        comment,
      },
      {
        onError,
        onSuccess: () => {
          setValue("");
          setComment("");
          toast({ title: t("common.success") });
        },
      },
    );
  };

  return (
    <div className="grid gap-3 rounded-lg border border-border/60 bg-muted/30 p-4 md:grid-cols-6">
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{t("silence.kind")}</span>
        <Select value={kind} onValueChange={(v) => { setKind(v as Kind); setValue(""); }}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="service">{t("silence.service")}</SelectItem>
            <SelectItem value="server">{t("silence.server")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="flex flex-col gap-1 md:col-span-2">
        <span className="text-xs text-muted-foreground">{t("silence.target")}</span>
        <Input
          list="silence-target-choices"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={LABEL[kind]}
        />
        <datalist id="silence-target-choices">
          {(choices.data?.data ?? []).map((c) => (
            <option key={c} value={c} />
          ))}
        </datalist>
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{t("silence.starts")}</span>
        <Input type="datetime-local" value={starts} onChange={(e) => setStarts(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{t("silence.ends")}</span>
        <Input type="datetime-local" value={ends} onChange={(e) => setEnds(e.target.value)} />
      </div>
      <div className="flex items-end">
        <Button onClick={submit} disabled={create.isPending || !value || !starts || !ends}>
          {t("silence.create")}
        </Button>
      </div>
      <div className="flex flex-col gap-1 md:col-span-6">
        <span className="text-xs text-muted-foreground">{t("silence.comment")}</span>
        <Input value={comment} onChange={(e) => setComment(e.target.value)} />
      </div>
    </div>
  );
}
