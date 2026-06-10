import { Badge } from "@/components/ui/badge";

type SyncStatus = "ok" | "pending" | "failed";

const variants: Record<SyncStatus, "success" | "warning" | "destructive"> = {
  ok: "success",
  pending: "warning",
  failed: "destructive",
};

export function StatusBadge({ status }: { status: SyncStatus | string }) {
  const variant = variants[status as SyncStatus] ?? "secondary";
  return <Badge variant={variant}>{status}</Badge>;
}

const severityVariants: Record<
  string,
  "destructive" | "warning" | "secondary"
> = {
  critical: "destructive",
  warning: "warning",
  info: "secondary",
};

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <Badge variant={severityVariants[severity] ?? "secondary"}>
      {severity}
    </Badge>
  );
}
