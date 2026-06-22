/** Human-readable server identity from alert labels (IMP). Group/key by cmdb_ci
 *  internally, but DISPLAY hostname (+ ip:port). Label keys vary by source, so
 *  each getter tries a priority list. */

export type Labels = Record<string, string> | null | undefined;

const HOST_KEYS = ["cmdb_hostname", "hostname", "host", "instance", "node"];
const IP_KEYS = ["client_address", "cmdb_ip", "ip", "address"];

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
export const cmdbCiFromLabels = (labels: Labels) => labels?.cmdb_ci;
