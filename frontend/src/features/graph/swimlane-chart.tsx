/** Incident swimlane renderer: plain React → SVG, system fonts only (air-gap).
 *
 *  X = time. One lane per INCIDENT (label = incident title). Inside each lane,
 *  the incident's member alerts render as time-positioned pills colored by
 *  severity. Selecting a pill or the lane label bubbles the incident up to the
 *  page for the detail panel. No edges/arcs — the model is incident-centric.
 */

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { scaleTime } from "d3-scale";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { GRAPH_MAX_VISIBLE_LANES } from "@/features/graph/config";
import { buildSwimlanes } from "@/features/graph/swimlanes";
import type { GraphData, GraphIncident } from "@/types";

const GUTTER_W = 260; // incident-title column
const AXIS_H = 28;
const ROW_H = 24;
const LANE_VPAD = 7;
const PILL_H = 14;
const PILL_MIN_W = 9;

const SEVERITY_FILL: Record<string, string> = {
  critical: "hsl(var(--sev-critical))",
  warning: "hsl(var(--sev-warning))",
  info: "hsl(var(--sev-info))",
};
const SEVERITY_FALLBACK = "hsl(var(--sev-neutral))";
const SELECTED_STROKE = "hsl(var(--foreground))";

interface SwimlaneChartProps {
  data: GraphData;
  selectedId: string | null;
  onSelect: (incident: GraphIncident | null) => void;
}

export function SwimlaneChart({ data, selectedId, onSelect }: SwimlaneChartProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [expanded, setExpanded] = useState(false);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const innerW = Math.max(width - GUTTER_W - 16, 100);

  const model = useMemo(() => {
    const probe = buildSwimlanes(data, {
      maxVisibleLanes: GRAPH_MAX_VISIBLE_LANES,
      expanded,
    });
    const msPerPx = (probe.domain[1] - probe.domain[0]) / innerW;
    return buildSwimlanes(data, {
      maxVisibleLanes: GRAPH_MAX_VISIBLE_LANES,
      expanded,
      minSeparationMs: msPerPx * (PILL_MIN_W + 3),
    });
  }, [data, expanded, innerW]);

  const [minMs, maxMs] = model.domain;
  const pad = (maxMs - minMs) * 0.03;
  const x = scaleTime()
    .domain([new Date(minMs - pad), new Date(maxMs + pad)])
    .range([GUTTER_W, GUTTER_W + innerW]);

  const laneTops: number[] = [];
  let cursor = AXIS_H;
  for (const lane of model.lanes) {
    laneTops.push(cursor);
    cursor += lane.rowCount * ROW_H + LANE_VPAD * 2;
  }
  const chartH = cursor;

  if (model.lanes.length === 0) {
    return (
      <div ref={containerRef} className="flex h-full items-center justify-center">
        <p className="text-sm text-muted-foreground">{t("graph.noData")}</p>
      </div>
    );
  }

  const ticks = x.ticks(Math.max(2, Math.floor(innerW / 110)));
  const fmt = x.tickFormat();

  return (
    <div
      ref={containerRef}
      className="h-full overflow-y-auto"
      data-testid="swimlane-chart"
      onClick={() => onSelect(null)}
    >
      <svg width={Math.max(width, GUTTER_W + 120)} height={chartH} className="block">
        {/* time axis + grid */}
        {ticks.map((tick) => (
          <g key={+tick}>
            <line
              x1={x(tick)}
              x2={x(tick)}
              y1={AXIS_H}
              y2={chartH}
              className="stroke-border"
              strokeDasharray="2 4"
            />
            <text
              x={x(tick)}
              y={AXIS_H - 10}
              textAnchor="middle"
              className="fill-muted-foreground text-[10px]"
            >
              {fmt(tick)}
            </text>
          </g>
        ))}

        {/* lanes (one per incident) */}
        {model.lanes.map((lane, i) => {
          const top = laneTops[i];
          const h = lane.rowCount * ROW_H + LANE_VPAD * 2;
          const isSelected = lane.incident.id === selectedId;
          return (
            <g key={lane.incident.id} data-testid={`lane-${lane.incident.id}`}>
              {(i % 2 === 1 || isSelected) && (
                <rect
                  x={0}
                  y={top}
                  width="100%"
                  height={h}
                  className={isSelected ? "fill-accent/40" : "fill-muted/40"}
                />
              )}
              <line x1={0} x2="100%" y1={top + h} y2={top + h} className="stroke-border" />
              <text
                x={10}
                y={top + h / 2 + 4}
                className="cursor-pointer fill-foreground text-xs font-medium"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(lane.incident);
                }}
              >
                <title>{lane.incident.title}</title>
                {lane.incident.title.slice(0, 34)}
                <tspan className="fill-muted-foreground font-normal">
                  {" "}({lane.incident.alert_count})
                </tspan>
              </text>
            </g>
          );
        })}

        {/* alert pills inside each incident lane */}
        {model.lanes.map((lane, i) =>
          lane.pills.map((pill) => {
            const px = x(pill.atMs);
            const py =
              laneTops[i] + LANE_VPAD + pill.row * ROW_H + (ROW_H - PILL_H) / 2;
            const pw = PILL_MIN_W;
            return (
              <g
                key={pill.alert.id}
                data-testid="alert-pill"
                data-incident-id={lane.incident.id}
                className="cursor-pointer"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(lane.incident);
                }}
              >
                <title>
                  {`${pill.alert.name}\n${pill.alert.severity} · ${
                    pill.alert.cmdb_hostname ?? ""
                  } · ×${pill.alert.dedup_count}`}
                </title>
                <rect
                  x={px}
                  y={py}
                  width={pw}
                  height={PILL_H}
                  rx={3}
                  fill={SEVERITY_FILL[pill.alert.severity] ?? SEVERITY_FALLBACK}
                  fillOpacity={pill.alert.status === "resolved" ? 0.4 : 0.95}
                  stroke={lane.incident.id === selectedId ? SELECTED_STROKE : "none"}
                  strokeWidth={1.5}
                />
              </g>
            );
          }),
        )}
      </svg>

      {model.hiddenLaneCount > 0 && !expanded && (
        <Button
          size="sm"
          variant="ghost"
          className="m-2 text-muted-foreground"
          data-testid="lane-expander"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(true);
          }}
        >
          {t("graph.laneMore", { count: model.hiddenLaneCount })}
        </Button>
      )}
      {expanded && (
        <Button
          size="sm"
          variant="ghost"
          className="m-2 text-muted-foreground"
          data-testid="lane-collapse"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(false);
          }}
        >
          {t("graph.showLess")}
        </Button>
      )}
    </div>
  );
}
