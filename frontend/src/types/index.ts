export interface Envelope<T> {
  data: T;
  error: ApiError | null;
  meta: Meta | null;
}

export interface ApiError {
  code: string;
  message: string;
  details?: unknown;
}

export interface Meta {
  next_cursor: string | null;
  has_more?: boolean;
}

export type GlobalRole = "admin" | "editor" | "viewer";
export type AuthProvider = "local" | "oidc";
export type ScopeType = "global" | "server" | "user" | "group";
export type Severity = "critical" | "warning" | "info";
export type Datasource = "metrics" | "logs";
export type SyncStatus = "ok" | "pending" | "failed";
export type ReceiverType = "slack" | "email" | "webhook" | "pagerduty";

export interface User {
  id: string;
  email: string;
  username: string;
  role: GlobalRole;
  auth_provider: AuthProvider;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  tenant_id: string | null;
  groups: GroupMembership[];
}

export interface Tenant {
  id: string;
  slug: string;
  name: string;
  is_active: boolean;
  mimir_orgs: string[];
  created_at: string;
  ingest_key?: string; // present only in the create response
}

export interface GroupMembership {
  group_id: string;
  group_name: string;
  role_in_group: "member" | "manager";
}

export interface Group {
  id: string;
  name: string;
  description: string | null;
  member_count?: number;
  created_at: string;
}

export interface GroupMember {
  user_id: string;
  username: string;
  email: string;
  role_in_group: "member" | "manager";
}

export interface Server {
  id: string;
  name: string;
  cmdb_ci: string | null;
  labels: Record<string, string>;
  description: string | null;
  owner_group_id: string | null;
  server_group_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AlertRule {
  id: string;
  name: string;
  description: string | null;
  scope_type: ScopeType;
  scope_ref_id: string | null;
  expr: string;
  for_duration: string;
  severity: Severity;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  enabled: boolean;
  datasource: Datasource;
  created_at: string;
  updated_at: string;
  created_by: string | null;
}

export interface RuleGroup {
  id: string;
  name: string;
  namespace: string;
  interval: string;
  tenant: string;
  rule_count?: number;
  rules?: AlertRule[];
  created_at: string;
}

export interface Receiver {
  id: string;
  name: string;
  type: ReceiverType;
  config: Record<string, unknown>;
  created_at: string;
}

export interface NotificationPolicy {
  id: string;
  matcher: Record<string, string>;
  receiver_id: string;
  group_by: string[];
  repeat_interval: string;
  created_at: string;
}

export interface Silence {
  id: string;
  matchers: Record<string, string>;
  starts_at: string;
  ends_at: string;
  comment: string;
  created_by: string | null;
  created_at: string;
}

export interface SyncState {
  id: string;
  target: "ruler" | "alertmanager";
  last_synced_at: string | null;
  status: SyncStatus;
  last_error: string | null;
  checksum: string | null;
}

export interface AuditLog {
  id: string;
  actor_id: string | null;
  actor_name?: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  before: unknown;
  after: unknown;
  ip: string | null;
  emergency: boolean;
  created_at: string;
}

export interface ActiveAlert {
  fingerprint: string;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  status: { state: string; silencedBy: string[]; inhibitedBy: string[] };
  startsAt: string;
  endsAt: string;
}

export interface CorrelationConfig {
  dedup_window_seconds: number;
  correlation_window_seconds: number;
  group_attrs: string[];
}

export interface NotificationSettings {
  telegram_bot_token: string | null;
  telegram_rate_per_second: number;
  quota_group_per_hour: number;
  quota_global_per_day: number;
  pending_softcap: number;
}

export interface NotificationRoute {
  id: string;
  group_id: string;
  min_severity: Severity;
  channels: string[];
  enabled: boolean;
  created_at: string;
}

export interface Recipient {
  user_id: string;
  username: string;
  email: string;
  telegram_chat_id: string | null;
  groups: string[];
}

export type IncidentStatus = "open" | "acknowledged" | "resolved" | "suppressed";

// IMP: a stored alert (every inbound alert, browsable on its own)
export interface StoredAlert {
  id: string;
  fingerprint: string;
  source: string;
  name: string;
  severity: string;
  status: string;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  starts_at: string;
  received_at: string;
  dedup_count: number;
  incident_id: string | null;
  cmdb_ci: string | null;
  cmdb_hostname: string | null;
  cmdb_zone: string | null;
  client_address: string | null;
  cmdb_service_l1_code: string | null;
  cmdb_service_l2_code: string | null;
  value: number | null;
  suppressed: boolean;
  correlated: boolean;
}

export interface Incident {
  id: string;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  tenant_id: string | null;
  group_key: string | null;
  first_seen: string;
  last_seen: string;
  alert_count: number;
  created_at: string;
  origin: string;
  cmdb_service_l2_code: string | null;
  cmdb_service_l1_code: string | null;
  cmdb_zone: string | null;
  notify_email: boolean;
  notify_telegram: boolean;
  notify_oncall: boolean;
  grouping_rule_id: string | null;
}

export interface IncidentDetail extends Incident {
  alerts: StoredAlert[];
  timeline: { id: string; kind: string; payload: Record<string, unknown>; created_at: string }[];
}

export interface GroupingRule {
  id: string;
  name: string;
  enabled: boolean;
  priority: number;
  label_keys: string[];
  window_seconds: number;
  min_group_size: number;
  critical_immediate: boolean;
  dedup_window_seconds: number;
}

export interface NotificationDefaults {
  default_email: boolean;
  default_telegram: boolean;
  default_oncall: boolean;
}

export interface AlertGroupCount {
  value: string;
  count: number;
}

export interface NotificationRow {
  id: string;
  incident_id: string;
  channel: string;
  recipient_address: string;
  status: string;
  attempts: number;
  retry_at: string | null;
  sent_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface StatsOverview {
  incidents: Record<IncidentStatus, number>;
  open_by_severity: Record<Severity, number>;
  notifications: Record<"pending" | "sent" | "failed" | "dead", number>;
  alerts_24h: number;
}

export interface TrendBucket {
  bucket: string;
  critical: number;
  warning: number;
  info: number;
}

export interface HostStat {
  group_key: string;
  open: number;
  total: number;
  alerts: number;
  max_severity: Severity;
  last_seen: string | null;
}

export interface GraphNode {
  id: string;
  kind: "incident" | "host" | "alert";
  label: string;
  severity: string | null;
  status: string | null;
  alert_count?: number;
  group_key?: string | null;
  first_seen?: string;
  last_seen?: string;
  dominant_name?: string | null;
  source?: string;
  dedup_count?: number;
  received_at?: string;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: "host" | "temporal" | "same_name" | "member";
  weight: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  meta: { truncated: boolean; total_incidents: number };
}

export interface HostSearchResult { host: string; incidents: number; last_seen: string | null; }
export interface LabelSearchResult {
  alert_event_id: string; name: string; severity: string;
  incident_id: string | null; labels: Record<string, string>; received_at: string;
}
export interface TextSearchResult {
  incident_id: string; title: string; severity: string; status: string;
  group_key: string | null; last_seen: string;
}
export interface SearchResponse {
  type: "host" | "label" | "text";
  results: (HostSearchResult | LabelSearchResult | TextSearchResult)[];
  error?: string;
}
export interface IncidentAnalysis {
  incident_id: string; status: "pending" | "running" | "done" | "failed";
  summary: string | null; root_cause: string | null; model: string | null;
  tokens_used: number; error: string | null; completed_at: string | null;
}
export interface LLMConfig {
  enabled: boolean; base_url: string; api_key: string | null; model: string;
  max_prompt_chars: number; max_completion_tokens: number; daily_quota: number;
  auto_analyze: boolean; redact_external_strict: boolean;
}
