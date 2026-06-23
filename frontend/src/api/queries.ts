import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { api } from "@/api/client";
import type {
  ActiveAlert,
  IncidentAnalysis,
  HostStat,
  Incident,
  IncidentDetail,
  NotificationRow,
  StatsOverview,
  TrendBucket,
  NotificationSettings,
  Recipient,
  AuditLog,
  Envelope,
  Group,
  GroupMember,
  NotificationPolicy,
  PulledRule,
  Receiver,
  Silence,
  User,
} from "@/types";

type Params = Record<string, string | undefined>;

function useList<T>(
  key: unknown[],
  path: string,
  params?: Params,
  options?: Partial<UseQueryOptions<Envelope<T[]>>>,
) {
  return useQuery<Envelope<T[]>>({
    queryKey: [...key, params],
    queryFn: () => api.get<T[]>(path, params),
    ...options,
  });
}

export function useInvalidate() {
  const qc = useQueryClient();
  return (key: string) => qc.invalidateQueries({ queryKey: [key] });
}

// --- Rules pulled from the Mimir Ruler (read-only) ---
export const useRulesPulled = () =>
  useList<PulledRule>(["rules-pulled"], "/rules/pulled");

// --- Threshold overrides (no PromQL: pick a pulled rule, edit a number) ---
export const useThresholdOverrides = () =>
  useQuery({
    queryKey: ["threshold-overrides"],
    queryFn: () => api.get<import("@/types").ThresholdOverride[]>("/threshold-overrides"),
  });

// --- Label autocomplete (whole-infra label names + values) ---
export const useLabelNames = () =>
  useQuery({
    queryKey: ["labels"],
    queryFn: () => api.get<string[]>("/labels"),
    staleTime: 5 * 60_000,
  });
export const useLabelValues = (name: string | null) =>
  useQuery({
    queryKey: ["labels", name, "values"],
    queryFn: () => api.get<string[]>(`/labels/${encodeURIComponent(name as string)}/values`),
    enabled: !!name,
    staleTime: 5 * 60_000,
  });

// --- Groups / Users ---
export const useGroups = (params?: Params) => useList<Group>(["groups"], "/groups", params);
export const useGroupMembers = (id: string) =>
  useQuery({
    queryKey: ["groups", id, "members"],
    queryFn: () => api.get<GroupMember[]>(`/groups/${id}/members`),
  });
export const useUsers = (params?: Params) => useList<User>(["users"], "/users", params);

// --- Notifications ---
export const useReceivers = (params?: Params) =>
  useList<Receiver>(["receivers"], "/receivers", params);
export const usePolicies = () =>
  useList<NotificationPolicy>(["notification-policies"], "/notification-policies");
export const useSilences = () => useList<Silence>(["silences"], "/silences");

export const useNotificationSettings = () =>
  useQuery({
    queryKey: ["notification-settings"],
    queryFn: () => api.get<NotificationSettings>("/notification-settings"),
  });
export const useRecipients = () =>
  useList<Recipient>(["notification-recipients"], "/notification-recipients");

// --- Ops dashboard (auto-refresh) ---
const OPS_REFRESH_MS = 10_000;

export const useIncidents = (params?: Params) =>
  useQuery({
    queryKey: ["incidents", params],
    queryFn: () => api.get<Incident[]>("/incidents", params),
    refetchInterval: OPS_REFRESH_MS,
  });
export const useIncident = (id: string | null) =>
  useQuery({
    queryKey: ["incidents", id],
    queryFn: () => api.get<IncidentDetail>(`/incidents/${id}`),
    enabled: !!id,
  });
export const useIncidentAnalysis = (id: string | null) =>
  useQuery({
    queryKey: ["incident-analysis", id],
    queryFn: () => api.get<IncidentAnalysis | null>(`/incidents/${id}/analysis`),
    enabled: !!id,
    refetchInterval: (query) => {
      const st = query.state.data?.data?.status;
      return st === "pending" || st === "running" ? 2000 : false;
    },
  });

export const useNotificationRows = (params?: Params) =>
  useQuery({
    queryKey: ["notifications", params],
    queryFn: () => api.get<NotificationRow[]>("/notifications", params),
    refetchInterval: OPS_REFRESH_MS,
  });

// --- IMP: alerts browse, grouping rules, notification defaults, l2 maps ---
export const useAlertsBrowse = (params?: Params) =>
  useQuery({
    queryKey: ["alerts-browse", params],
    queryFn: () => api.get<import("@/types").StoredAlert[]>("/alerts", params),
  });
export const useAlertGroups = (params?: Params) =>
  useQuery({
    queryKey: ["alert-groups", params],
    queryFn: () => api.get<import("@/types").AlertGroupCount[]>("/alerts", params),
  });
export const useGroupingRules = () =>
  useQuery({
    queryKey: ["grouping-rules"],
    queryFn: () => api.get<import("@/types").GroupingRule[]>("/grouping-rules"),
  });
export const useNotificationDefaults = () =>
  useQuery({
    queryKey: ["notification-defaults"],
    queryFn: () => api.get<import("@/types").NotificationDefaults>("/notification-defaults"),
  });
export const useGroupServiceCodes = (groupId: string | null) =>
  useQuery({
    queryKey: ["group-service-codes", groupId],
    queryFn: () => api.get<{ codes: string[] }>(`/groups/${groupId}/service-codes`),
    enabled: !!groupId,
  });
export const useStatsOverview = () =>
  useQuery({
    queryKey: ["stats", "overview"],
    queryFn: () => api.get<StatsOverview>("/stats/overview"),
    refetchInterval: OPS_REFRESH_MS,
  });
export const useStatsTrend = (hours: number) =>
  useQuery({
    queryKey: ["stats", "trend", hours],
    queryFn: () =>
      api.get<{ bucket_seconds: number; buckets: TrendBucket[] }>("/stats/trend", {
        hours: String(hours),
      }),
    refetchInterval: OPS_REFRESH_MS,
  });
export const useStatsHosts = (sinceHours?: number) =>
  useQuery({
    queryKey: ["stats", "hosts", sinceHours],
    queryFn: () =>
      api.get<HostStat[]>(
        "/stats/hosts",
        sinceHours ? { since_hours: String(sinceHours) } : undefined,
      ),
    refetchInterval: OPS_REFRESH_MS,
  });

// --- Audit / Alerts ---
export const useAuditLogs = (params?: Params) =>
  useList<AuditLog>(["audit-logs"], "/audit-logs", params);
export const useActiveAlerts = () =>
  useQuery({
    queryKey: ["alerts", "active"],
    queryFn: () => api.get<ActiveAlert[]>("/alerts/active"),
    refetchInterval: 30_000,
    retry: 0,
  });

// --- Generic mutation helper ---
export function useApiMutation<TInput, TOutput = unknown>(
  fn: (input: TInput) => Promise<Envelope<TOutput>>,
  invalidateKeys: string[],
  onSuccess?: (data: Envelope<TOutput>) => void,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      for (const key of invalidateKeys) {
        qc.invalidateQueries({ queryKey: [key] });
      }
      onSuccess?.(data);
    },
  });
}
