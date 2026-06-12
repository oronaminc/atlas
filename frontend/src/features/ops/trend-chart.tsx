import type { TrendBucket } from "@/types";

const COLORS: Record<"critical" | "warning" | "info", string> = {
  critical: "hsl(0 84% 60%)",
  warning: "hsl(38 92% 50%)",
  info: "hsl(217 91% 60%)",
};

/** Dependency-free stacked bar chart (air-gapped target: no chart CDN/libs). */
export function TrendChart({ buckets }: { buckets: TrendBucket[] }) {
  const width = 720;
  const height = 160;
  const padding = 4;
  const max = Math.max(1, ...buckets.map((b) => b.critical + b.warning + b.info));
  const barWidth = (width - padding * 2) / Math.max(buckets.length, 1);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height + 18}`}
        className="h-44 w-full min-w-[480px]"
        role="img"
        aria-label="alert trend"
        data-testid="trend-chart"
      >
        {buckets.map((bucket, i) => {
          const total = bucket.critical + bucket.warning + bucket.info;
          let y = height;
          const segments = (["info", "warning", "critical"] as const).map((severity) => {
            const h = (bucket[severity] / max) * (height - 8);
            y -= h;
            return (
              <rect
                key={severity}
                x={padding + i * barWidth + 1}
                y={y}
                width={Math.max(barWidth - 2, 1)}
                height={h}
                fill={COLORS[severity]}
                rx={1}
              >
                <title>{`${bucket.bucket}\n${severity}: ${bucket[severity]}`}</title>
              </rect>
            );
          });
          return (
            <g key={bucket.bucket}>
              {segments}
              {total > 0 && (
                <text
                  x={padding + i * barWidth + barWidth / 2}
                  y={y - 3}
                  textAnchor="middle"
                  fontSize="9"
                  fill="currentColor"
                  opacity={0.7}
                >
                  {total}
                </text>
              )}
            </g>
          );
        })}
        <line
          x1={padding}
          y1={height}
          x2={width - padding}
          y2={height}
          stroke="currentColor"
          opacity={0.2}
        />
        {buckets.length > 0 && (
          <>
            <text x={padding} y={height + 14} fontSize="9" fill="currentColor" opacity={0.6}>
              {new Date(buckets[0].bucket).toLocaleString()}
            </text>
            <text
              x={width - padding}
              y={height + 14}
              textAnchor="end"
              fontSize="9"
              fill="currentColor"
              opacity={0.6}
            >
              {new Date(buckets[buckets.length - 1].bucket).toLocaleString()}
            </text>
          </>
        )}
      </svg>
      <div className="flex gap-4 text-xs text-muted-foreground">
        {(Object.keys(COLORS) as (keyof typeof COLORS)[]).map((severity) => (
          <span key={severity} className="flex items-center gap-1">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ backgroundColor: COLORS[severity] }}
            />
            {severity}
          </span>
        ))}
      </div>
    </div>
  );
}
