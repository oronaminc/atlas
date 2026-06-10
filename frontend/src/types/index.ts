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
  groups: GroupMembership[];
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
  labels: Record<string, string>;
  description: string | null;
  owner_group_id: string | null;
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
