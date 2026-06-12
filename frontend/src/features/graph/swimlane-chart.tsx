/** 2D swimlane renderer: plain React → SVG, system fonts only (air-gap safe).
 *
 *  X = time, one lane per host. Temporal edges are UNDIRECTED arcs — the
 *  data is proximity ("fired together"), not causality, so no arrowheads.
 *  same_name correlation stays hidden until a pill is hovered/selected to
 *  avoid re-cluttering during alert storms.
 */

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { scaleTime } from "d3-scale";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { GRAPH_MAX_VISIBLE_LANES } from "@/features/graph/config";
import { buildSwimlanes } from "@/features/graph/swimlanes";
import type { GraphData, GraphNode } from "@/types";

const GUTTER_W = 180; // host label column
const AXIS_H = 28;
const ROW_H = 26;
const LANE_VPAD = 7;
const PILL_H = 16;
const PILL_MIN_W = 8;

const SEVERITY_FILL: Record<string, string> = {
  critical: "#ef4444",
  warning: "#f59e0b",
  info: "#3b82f6",
};

interface SwimlaneChartProps {
  data: GraphData;
  selectedId: string | null;
  onSelect: (node: GraphNode | null) => void;
}

export function SwimlaneChart({ data, selectedId, onSelect }: SwimlaneChartProps) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [hoverId, setHoverId] = useState<string | null>(null);

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
    // stack pills that would collide at the current pixel density
    const probe = buildSwimlanes(data, {
      maxVisibleLanes: GRAPH_MAX_VISIBLE_LANES,
      expanded,
    });
    const msPerPx = (probe.domain[1] - probe.domain[0]) / innerW;
    return buildSwimlanes(data, {
      maxVisibleLanes: GRAPH_MAX_VISIBLE_LANES,
      expanded,
      minSeparationMs: msPerPx * (PILL_MIN_W + 4),
    });
  }, [data, expanded, innerW]);

  const [minMs, maxMs] = model.domain;
  const pad = (maxMs - minMs) * 0.03;
  const x = scaleTime()
    .domain([new Date(minMs - pad), new Date(maxMs + pad)])
    .range([GUTTER_W, GUTTER_W + innerW]);

  // lane offsets + pill anchor positions (for edge arcs)
  const laneTops: number[] = [];
  let cursor = AXIS_H;
  for (const lane of model.lanes) {
    laneTops.push(cursor);
    cursor += lane.rowCount * ROW_H + LANE_VPAD * 2;
  }
  const chartH = cursor;

  const anchor = new Map<string, { x: number; y: number }>();
  model.lanes.forEach((lane, i) => {
    for (const pill of lane.pills) {
      anchor.set(pill.node.id, {
        x: x(pill.startMs) + PILL_MIN_W / 2,
        y: laneTops[i] + LANE_VPAD + pill.row * ROW_H + ROW_H / 2,
      });
    }
  });

  const activeId = hoverId ?? selectedId;
  const partners = activeId ? model.sameNamePartners.get(activeId) : undefined;
  const related = activeId
    ? new Set([activeId, ...(partners ?? [])])
    : null;

  const arc = (a: { x: number; y: number }, b: { x: number; y: number }) => {
    const bend = a.y === b.y ? -Math.min(24, 10 + Math.abs(b.x - a.x) / 8) : 0;
    const my = (a.y + b.y) / 2 + bend;
    return `M ${a.x} ${a.y} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${b.y}`;
  };

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

        {/* lanes */}
        {model.lanes.map((lane, i) => {
          const top = laneTops[i];
          const h = lane.rowCount * ROW_H + LANE_VPAD * 2;
          return (
            <g key={lane.host || "(none)"} data-testid={`lane-${lane.host}`}>
              {i % 2 === 1 && (
                <rect x={0} y={top} width="100%" height={h} className="fill-muted/40" />
              )}
              <line x1={0} x2="100%" y1={top + h} y2={top + h} className="stroke-border" />
              <text
                x={10}
                y={top + h / 2 + 4}
                className="fill-foreground text-xs font-medium"
              >
                {(lane.host || t("graph.noHost")).slice(0, 24)}
                <tspan className="fill-muted-foreground font-normal">
                  {" "}({lane.pills.length})
                </tspan>
              </text>
            </g>
          );
        })}

        {/* temporal arcs — undirected: proximity, not causality */}
        {model.temporalEdges.map((edge, i) => {
          const a = anchor.get(edge.source.id);
          const b = anchor.get(edge.target.id);
          if (!a || !b) return null;
          const touched =
            !related || related.has(edge.source.id) || related.has(edge.target.id);
          return (
            <path
              key={`t${i}`}
              d={arc(a, b)}
              fill="none"
              stroke="#22d3ee"
              strokeWidth={1.2}
              opacity={(0.35 + edge.weight * 0.45) * (touched ? 1 : 0.15)}
            />
          );
        })}

        {/* same_name arcs — only while hovering/selected */}
        {activeId &&
          [...(partners ?? [])].map((partnerId) => {
            const a = anchor.get(activeId);
            const b = anchor.get(partnerId);
            if (!a || !b) return null;
            return (
              <path
                key={`s${partnerId}`}
                d={arc(a, b)}
                fill="none"
                stroke="#a78bfa"
                strokeWidth={1.6}
                strokeDasharray="5 3"
                data-testid="same-name-arc"
              />
            );
          })}

        {/* incident pills */}
        {model.lanes.map((lane, i) =>
          lane.pills.map((pill) => {
            const px = x(pill.startMs);
            const pw = Math.max(x(pill.endMs) - px, PILL_MIN_W);
            const py =
              laneTops[i] + LANE_VPAD + pill.row * ROW_H + (ROW_H - PILL_H) / 2;
            const dimmed = related !== null && !related.has(pill.node.id);
            const highlighted = related !== null && related.has(pill.node.id);
            return (
              <g
                key={pill.node.id}
                data-testid="incident-pill"
                data-incident-id={pill.node.id}
                className="cursor-pointer"
                opacity={dimmed ? 0.25 : 1}
                onMouseEnter={() => setHoverId(pill.node.id)}
                onMouseLeave={() => setHoverId(null)}
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(pill.node);
                }}
              >
                <title>
                  {`${pill.node.label}\n${pill.node.severity ?? ""} · ×${pill.node.alert_count ?? 0}`}
                </title>
                <rect
                  x={px}
                  y={py}
                  width={pw}
                  height={PILL_H}
                  rx={4}
                  fill={SEVERITY_FILL[pill.node.severity ?? ""] ?? "#64748b"}
                  fillOpacity={pill.node.status === "resolved" ? 0.4 : 0.9}
                  stroke={
                    pill.node.id === selectedId
                      ? "#ffffff"
                      : highlighted
                        ? "#a78bfa"
                        : "none"
                  }
                  strokeWidth={pill.node.id === selectedId ? 2 : 1.5}
                />
                {pw > 40 && (
                  <text
                    x={px + 5}
                    y={py + PILL_H - 4}
                    className="pointer-events-none fill-white text-[10px]"
                  >
                    {pill.node.label.slice(0, Math.floor(pw / 7))}
                    {(pill.node.alert_count ?? 0) > 1 ? ` ×${pill.node.alert_count}` : ""}
                  </text>
                )}
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
