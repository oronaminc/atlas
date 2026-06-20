/** Human-readable server identity. We group/key by cmdb_ci internally, but the
 *  UI must DISPLAY a hostname (+ ip:port) — never a raw cmdb_ci as the primary
 *  label. cmdb_ci stays secondary (subtext / tooltip). Real label keys vary by
 *  source, so each getter tries a priority list of candidates. */

export type Labels = Record<string, string> | null | undefined;

const HOST_KEYS = ["cmdb_hostname", "hostname", "host", "node", "nodename", "kubernetes_node"];
const IP_KEYS = ["instance", "cmdb_ip", "ip", "ipaddr", "address"];
const SERVICE_KEYS = ["cmdb_service_l1", "cmdb_service", "service", "cmdb_app", "app", "job"];
const ENV_KEYS = ["cmdb_env", "environment", "env", "stage"];

function firstOf(labels: Labels, keys: string[]): string | undefined {
  if (!labels) return undefined;
  for (const k of keys) {
    const v = labels[k];
    if (v) return v;
  }
  return undefined;
}

export const hostnameFromLabels = (labels: Labels) => firstOf(labels, HOST_KEYS);
export const instanceFromLabels = (labels: Labels) => firstOf(labels, IP_KEYS);
export const serviceFromLabels = (labels: Labels) => firstOf(labels, SERVICE_KEYS);
export const envFromLabels = (labels: Labels) => firstOf(labels, ENV_KEYS);
export const cmdbCiFromLabels = (labels: Labels) => labels?.cmdb_ci;

/** "host=web-02.sktelecom.com" -> "web-02.sktelecom.com"; passthrough if no "=". */
export function stripGroupKey(groupKey: string | null | undefined): string {
  if (!groupKey) return "";
  const i = groupKey.indexOf("=");
  return i === -1 ? groupKey : groupKey.slice(i + 1);
}

/** Best display label for a server given its labels + a fallback (e.g. the
 *  incident group_key). Prefers hostname, then the fallback, then cmdb_ci. */
export function displayHost(labels: Labels, fallback?: string | null): string {
  return hostnameFromLabels(labels) ?? stripGroupKey(fallback) ?? cmdbCiFromLabels(labels) ?? "—";
}
