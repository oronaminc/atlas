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
  // numbered pagination (audit-logs, users with ?page=)
  total?: number;
  page?: number;
  pages?: number;
  page_size?: number;
}

export type GlobalRole = "admin" | "editor" | "viewer";
export type AuthProvider = "local" | "oidc";
export type Severity = "critical" | "warning" | "info";
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
  groups: GroupMembership[];
}

// Read-only rule pulled from the Mimir Ruler (the alertname catalog source).
// `expr` is DISPLAY-ONLY read-only text — never an input (no PromQL anywhere).
export interface PulledRule {
  alertname: string;
  expr: string;
  for_seconds: number | null;
  severity: string | null;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  namespace: string;
  group_name: string;
  health: string | null;
  state: string | null;
  last_error: string | null;
  last_evaluation: string | null;
  value: number | null;
  base_threshold: number | null;
  comparator: string | null;
  synced_at: string | null;
}

export interface ThresholdOverride {
  id: string;
  alertname: string;
  target_cmdb_ci: string | null;
  target_label_key: string | null;
  target_label_value: string | null;
  value: number;
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
  labels?: string[];
  member_count?: number;
  created_at: string;
}

export interface GroupMember {
  user_id: string;
  username: string;
  email: string;
  role_in_group: "member" | "manager";
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

export interface SilenceMatcher {
  name: string;
  value: string;
  isRegex?: boolean;
  isEqual?: boolean;
}

export interface Silence {
  silence_id: string;
  matchers: SilenceMatcher[];
  starts_at: string | null;
  ends_at: string | null;
  comment: string | null;
  created_by_label: string | null;
  state: string | null;
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

export interface GroupChannel {
  id: string;
  channel: "telegram" | "email" | "oncall";
  enabled: boolean;
  chat_id: string | null;
  email: string | null;
  bot_token: string | null; // MASKED when set
  webhook_url: string | null; // MASKED when set
  oncall_token: string | null; // MASKED when set
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
  host: string;
  open: number;
  total: number;
  alerts: number;
  max_severity: Severity;
  last_seen: string | null;
}

// --- Incident-centric swimlane graph (node/edge model is GONE) ---
export interface GraphAlert {
  id: string;
  name: string;
  severity: string;
  status: string;
  received_at: string;
  cmdb_hostname: string | null;
  dedup_count: number;
}

export interface GraphIncident {
  id: string;
  title: string;
  severity: string;
  status: string;
  first_seen: string;
  last_seen: string;
  alert_count: number;
  cmdb_service_l2_code: string | null;
  alerts: GraphAlert[];
}

export interface GraphData {
  incidents: GraphIncident[];
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
