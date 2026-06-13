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
  Tenant,
  CorrelationConfig,
  HostStat,
  Incident,
  IncidentDetail,
  NotificationRow,
  StatsOverview,
  TrendBucket,
  NotificationRoute,
  NotificationSettings,
  Recipient,
  AlertRule,
  AuditLog,
  Envelope,
  Group,
  GroupMember,
  NotificationPolicy,
  Receiver,
  RuleGroup,
  Server,
  Silence,
  SyncState,
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

// --- Servers ---
export const useServers = (params?: Params) =>
  useList<Server>(["servers"], "/servers", params);
export const useServer = (id: string) =>
  useQuery({
    queryKey: ["servers", id],
    queryFn: () => api.get<Server>(`/servers/${id}`),
  });
export const useServerRules = (id: string) =>
  useQuery({
    queryKey: ["servers", id, "rules"],
    queryFn: () => api.get<AlertRule[]>(`/servers/${id}/rules`),
  });

// --- Rules ---
export const useRules = (params?: Params) => useList<AlertRule>(["rules"], "/rules", params);
export const useRule = (id: string | undefined) =>
  useQuery({
    queryKey: ["rules", id],
    queryFn: () => api.get<AlertRule>(`/rules/${id}`),
    enabled: !!id,
  });

// --- Rule groups ---
export const useRuleGroups = (params?: Params) =>
  useList<RuleGroup>(["rule-groups"], "/rule-groups", params);
export const useRuleGroup = (id: string | undefined) =>
  useQuery({
    queryKey: ["rule-groups", id],
    queryFn: () => api.get<RuleGroup>(`/rule-groups/${id}`),
    enabled: !!id,
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

// --- Correlation config ---
export const useCorrelationConfig = () =>
  useQuery({
    queryKey: ["correlation-config"],
    queryFn: () => api.get<CorrelationConfig>("/correlation-config"),
  });

export const useNotificationSettings = () =>
  useQuery({
    queryKey: ["notification-settings"],
    queryFn: () => api.get<NotificationSettings>("/notification-settings"),
  });
export const useNotificationRoutes = () =>
  useList<NotificationRoute>(["notification-routes"], "/notification-routes");
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
export const useStatsOverview = (tenant?: string) =>
  useQuery({
    queryKey: ["stats", "overview", tenant],
    queryFn: () => api.get<StatsOverview>("/stats/overview", tenant ? { tenant } : undefined),
    refetchInterval: OPS_REFRESH_MS,
  });
export const useStatsTrend = (hours: number, tenant?: string) =>
  useQuery({
    queryKey: ["stats", "trend", hours, tenant],
    queryFn: () =>
      api.get<{ bucket_seconds: number; buckets: TrendBucket[] }>("/stats/trend", {
        hours: String(hours),
        ...(tenant ? { tenant } : {}),
      }),
    refetchInterval: OPS_REFRESH_MS,
  });
export const useStatsHosts = (tenant?: string) =>
  useQuery({
    queryKey: ["stats", "hosts", tenant],
    queryFn: () => api.get<HostStat[]>("/stats/hosts", tenant ? { tenant } : undefined),
    refetchInterval: OPS_REFRESH_MS,
  });

// --- Tenants ---
export const useTenants = () => useList<Tenant>(["tenants"], "/tenants");

// --- Sync / Audit / Alerts ---
export const useSyncState = () =>
  useQuery({
    queryKey: ["sync-state"],
    queryFn: () => api.get<SyncState[]>("/sync-state"),
    refetchInterval: 15_000,
  });
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
