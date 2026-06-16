import { cn } from "@/lib/utils";

/** Status + severity chips. Color is NEVER the only signal: severity always
 *  carries a shape glyph (●/▲/■) so it stays readable for colorblind users. */

type SyncStatus = "ok" | "pending" | "failed";

const statusStyles: Record<string, string> = {
  ok: "bg-status-ok/15 text-status-ok",
  pending: "bg-severity-warning/15 text-severity-warning",
  failed: "bg-severity-critical/15 text-severity-critical",
};

const chip =
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold";

export function StatusBadge({ status }: { status: SyncStatus | string }) {
  return (
    <span
      className={cn(
        chip,
        statusStyles[status] ?? "bg-secondary text-secondary-foreground",
      )}
    >
      {status}
    </span>
  );
}

const severityStyles: Record<string, { cls: string; icon: string }> = {
  critical: { cls: "bg-severity-critical/15 text-severity-critical", icon: "●" },
  warning: { cls: "bg-severity-warning/15 text-severity-warning", icon: "▲" },
  info: { cls: "bg-severity-info/15 text-severity-info", icon: "■" },
};

export function SeverityBadge({ severity }: { severity: string }) {
  const s = severityStyles[severity] ?? {
    cls: "bg-secondary text-secondary-foreground",
    icon: "■",
  };
  return (
    <span className={cn(chip, s.cls)}>
      <span aria-hidden className="text-[0.7em] leading-none">
        {s.icon}
      </span>
      {severity}
    </span>
  );
}
