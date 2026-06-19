/** Notification targets & mutes (PR #1). Server groups (1:1 membership) with
 *  bulk cmdb_ci upload + per-(target × alertname) mute with a searchable rule
 *  picker and a "currently muted" view. Threshold overrides land in PR #2. */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { useApiMutation } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PageHeader } from "@/components/layout/page-header";
import { useAuth } from "@/hooks/use-auth";
import { useToast } from "@/hooks/use-toast";

interface ServerGroup {
  id: string;
  name: string;
  member_count: number;
}
interface Mute {
  id: string;
  target_type: string;
  target_cmdb_ci: string | null;
  target_group_id: string | null;
  alertname: string | null;
}

export function MutesPage() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const { hasRole } = useAuth();
  const canEdit = hasRole("admin", "editor");

  const groups = useQuery({
    queryKey: ["server-groups"],
    queryFn: () => api.get<ServerGroup[]>("/server-groups"),
  });
  const catalog = useQuery({
    queryKey: ["rule-catalog"],
    queryFn: () => api.get<{ alertnames: string[] }>("/mutes/rule-catalog"),
  });
  const mutes = useQuery({
    queryKey: ["mutes"],
    queryFn: () => api.get<Mute[]>("/mutes"),
  });

  const fail = (e: unknown) =>
    toast({
      variant: "destructive",
      title: t("common.failed"),
      description: e instanceof Error ? e.message : String(e),
    });

  // --- server group create + bulk upload ---
  const [groupName, setGroupName] = useState("");
  const createGroup = useApiMutation(
    () => api.post("/server-groups", { name: groupName }),
    ["server-groups"],
    () => setGroupName(""),
  );
  const [bulkGroup, setBulkGroup] = useState("");
  const [bulkText, setBulkText] = useState("");
  const bulkUpload = useApiMutation<void, { added: number; reassigned: number; rejected: string[] }>(
    () =>
      api.post(`/server-groups/${bulkGroup}/members/bulk`, {
        cmdb_cis: bulkText.split(/[\s,]+/).filter(Boolean),
      }),
    ["server-groups"],
  );

  // --- mute create ---
  const [ruleSearch, setRuleSearch] = useState("");
  const [alertname, setAlertname] = useState<string | null>(null);
  const [allRules, setAllRules] = useState(false);
  const [targetType, setTargetType] = useState<"server" | "group" | "all">("server");
  const [cmdb, setCmdb] = useState("");
  const [muteGroup, setMuteGroup] = useState("");

  const filteredRules = useMemo(() => {
    const all = catalog.data?.data.alertnames ?? [];
    const q = ruleSearch.trim().toLowerCase();
    return q ? all.filter((n) => n.toLowerCase().includes(q)) : all;
  }, [catalog.data, ruleSearch]);

  const createMute = useApiMutation(
    () =>
      api.post("/mutes", {
        target_type: targetType,
        target_cmdb_ci: targetType === "server" ? cmdb : null,
        target_group_id: targetType === "group" ? muteGroup : null,
        alertname: allRules ? null : alertname,
      }),
    ["mutes"],
  );
  const deleteMute = useApiMutation((id: string) => api.delete(`/mutes/${id}`), ["mutes"]);

  const groupName_ = (id: string | null) =>
    groups.data?.data.find((g) => g.id === id)?.name ?? id;

  const canSubmitMute =
    (allRules || !!alertname) &&
    ((targetType === "server" && !!cmdb) ||
      (targetType === "group" && !!muteGroup) ||
      (targetType === "all" && !allRules)); // 'all' target requires a specific rule

  return (
    <div data-testid="mutes-page" className="space-y-6">
      <PageHeader title={t("mutes.title")} description={t("mutes.description")} />

      {/* Server groups + bulk upload */}
      <Card data-testid="server-groups-card">
        <CardHeader>
          <CardTitle className="text-base">{t("mutes.serverGroups")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {canEdit && (
            <div className="flex gap-2">
              <Input
                className="max-w-xs"
                placeholder={t("mutes.groupNamePlaceholder")}
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                data-testid="sg-name-input"
              />
              <Button
                disabled={!groupName || createGroup.isPending}
                onClick={() => createGroup.mutate(undefined, { onError: fail })}
                data-testid="sg-create"
              >
                {t("mutes.createGroup")}
              </Button>
            </div>
          )}
          <ul className="space-y-1" data-testid="sg-list">
            {(groups.data?.data ?? []).map((g) => (
              <li
                key={g.id}
                data-testid="sg-row"
                className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm"
              >
                <span className="font-medium">{g.name}</span>
                <Badge variant="secondary" data-testid="sg-count">
                  {g.member_count} {t("mutes.members")}
                </Badge>
              </li>
            ))}
            {groups.data?.data.length === 0 && (
              <li className="text-sm text-muted-foreground" data-testid="sg-empty">
                {t("mutes.noGroups")}
              </li>
            )}
          </ul>

          {canEdit && (
            <div className="space-y-2 rounded-md border border-border/60 bg-muted/20 p-3">
              <div className="text-sm font-medium">{t("mutes.bulkUpload")}</div>
              <Select value={bulkGroup} onValueChange={setBulkGroup}>
                <SelectTrigger className="max-w-xs" data-testid="bulk-group-select">
                  <SelectValue placeholder={t("mutes.selectGroup")} />
                </SelectTrigger>
                <SelectContent>
                  {(groups.data?.data ?? []).map((g) => (
                    <SelectItem key={g.id} value={g.id} data-testid="bulk-group-option">
                      {g.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <textarea
                className="h-24 w-full rounded-md border border-input bg-background p-2 text-sm font-mono"
                placeholder={t("mutes.bulkPlaceholder")}
                value={bulkText}
                onChange={(e) => setBulkText(e.target.value)}
                data-testid="bulk-cmdb-input"
              />
              <Button
                disabled={!bulkGroup || !bulkText.trim() || bulkUpload.isPending}
                onClick={() =>
                  bulkUpload.mutate(undefined, {
                    onError: fail,
                    onSuccess: (d) =>
                      toast({
                        title: t("common.success"),
                        description: `+${d.data.added} / ↻${d.data.reassigned} / ✗${d.data.rejected.length}`,
                      }),
                  })
                }
                data-testid="bulk-upload"
              >
                {t("mutes.upload")}
              </Button>
              {bulkUpload.data && (
                <div className="text-xs text-muted-foreground" data-testid="bulk-result">
                  added {bulkUpload.data.data.added}, reassigned{" "}
                  {bulkUpload.data.data.reassigned}, rejected{" "}
                  {bulkUpload.data.data.rejected.length}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Mute manager */}
      <Card data-testid="mute-manager-card">
        <CardHeader>
          <CardTitle className="text-base">{t("mutes.muteRules")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {canEdit && (
            <div className="space-y-3 rounded-md border border-border/60 bg-muted/20 p-3">
              {/* searchable rule picker */}
              <div className="relative max-w-md">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  className="pl-8"
                  placeholder={t("mutes.searchRules")}
                  value={ruleSearch}
                  onChange={(e) => setRuleSearch(e.target.value)}
                  data-testid="rule-search"
                  disabled={allRules}
                />
              </div>
              {!allRules && (
                <div className="max-h-32 overflow-y-auto" data-testid="rule-options">
                  {filteredRules.map((n) => (
                    <button
                      key={n}
                      type="button"
                      onClick={() => setAlertname(n)}
                      data-testid="rule-option"
                      className={`block w-full rounded px-2 py-1 text-left text-sm hover:bg-accent ${
                        alertname === n ? "bg-accent text-accent-foreground" : ""
                      }`}
                    >
                      {n}
                    </button>
                  ))}
                  {filteredRules.length === 0 && (
                    <div className="px-2 py-1 text-sm text-muted-foreground" data-testid="rule-none">
                      {t("mutes.noRules")}
                    </div>
                  )}
                </div>
              )}
              <label className="flex items-center gap-2 text-sm" data-testid="all-rules-label">
                <input
                  type="checkbox"
                  checked={allRules}
                  onChange={(e) => setAllRules(e.target.checked)}
                  data-testid="mute-all-rules"
                />
                {t("mutes.allRules")}
              </label>

              <div className="flex flex-wrap items-center gap-2">
                <Select value={targetType} onValueChange={(v) => setTargetType(v as never)}>
                  <SelectTrigger className="w-40" data-testid="mute-target-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="server" data-testid="tt-server">
                      {t("mutes.targetServer")}
                    </SelectItem>
                    <SelectItem value="group" data-testid="tt-group">
                      {t("mutes.targetGroup")}
                    </SelectItem>
                    <SelectItem value="all" data-testid="tt-all">
                      {t("mutes.targetAll")}
                    </SelectItem>
                  </SelectContent>
                </Select>
                {targetType === "server" && (
                  <Input
                    className="w-64 font-mono"
                    placeholder="cmdb_ci"
                    value={cmdb}
                    onChange={(e) => setCmdb(e.target.value)}
                    data-testid="mute-cmdb-input"
                  />
                )}
                {targetType === "group" && (
                  <Select value={muteGroup} onValueChange={setMuteGroup}>
                    <SelectTrigger className="w-48" data-testid="mute-group-select">
                      <SelectValue placeholder={t("mutes.selectGroup")} />
                    </SelectTrigger>
                    <SelectContent>
                      {(groups.data?.data ?? []).map((g) => (
                        <SelectItem key={g.id} value={g.id}>
                          {g.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
                <Button
                  disabled={!canSubmitMute || createMute.isPending}
                  onClick={() =>
                    createMute.mutate(undefined, {
                      onError: fail,
                      onSuccess: () => toast({ title: t("mutes.muted") }),
                    })
                  }
                  data-testid="mute-create"
                >
                  {allRules ? t("mutes.muteAllBtn") : t("mutes.muteBtn")}
                </Button>
              </div>
            </div>
          )}

          {/* currently muted */}
          <div>
            <div className="mb-2 text-sm font-medium">{t("mutes.currentlyMuted")}</div>
            <ul className="space-y-1" data-testid="muted-list">
              {(mutes.data?.data ?? []).map((m) => (
                <li
                  key={m.id}
                  data-testid="muted-row"
                  className="flex items-center justify-between rounded-md border border-border/60 px-3 py-2 text-sm"
                >
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">{m.target_type}</Badge>
                    <span className="font-mono">
                      {m.target_cmdb_ci ?? groupName_(m.target_group_id) ?? "*"}
                    </span>
                    <span className="text-muted-foreground">·</span>
                    <span>{m.alertname ?? t("mutes.allRules")}</span>
                  </span>
                  {canEdit && (
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => deleteMute.mutate(m.id, { onError: fail })}
                      data-testid="unmute"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </li>
              ))}
              {mutes.data?.data.length === 0 && (
                <li className="text-sm text-muted-foreground" data-testid="muted-empty">
                  {t("mutes.noMutes")}
                </li>
              )}
            </ul>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
