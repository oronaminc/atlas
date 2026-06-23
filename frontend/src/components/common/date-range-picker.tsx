/** Shared date-range control (top-right). Presets (1h/6h/24h/7d/30d) emit a
 *  relative window resolved to absolute ISO strings at click time; "custom"
 *  reveals two datetime-local inputs for an absolute start+end.
 *
 *  Emits `{ start?, end?, label }` where start/end are ISO-8601 UTC strings
 *  (or undefined for an open bound). Dependency-free, system fonts (air-gap).
 */

import { useState } from "react";
import { CalendarRange, Check } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface DateRange {
  /** ISO-8601 UTC, or undefined for an open lower bound */
  start?: string;
  /** ISO-8601 UTC, or undefined for an open upper bound (= now) */
  end?: string;
  /** i18n key suffix under dateRange.* for the active preset, or "custom" */
  label: string;
}

interface Preset {
  key: string;
  hours: number;
}

const PRESETS: Preset[] = [
  { key: "1h", hours: 1 },
  { key: "6h", hours: 6 },
  { key: "24h", hours: 24 },
  { key: "7d", hours: 24 * 7 },
  { key: "30d", hours: 24 * 30 },
];

/** Resolve a relative preset to an absolute range ending at "now". */
export function resolvePreset(hours: number, key: string): DateRange {
  const now = Date.now();
  return {
    start: new Date(now - hours * 3_600_000).toISOString(),
    end: new Date(now).toISOString(),
    label: key,
  };
}

/** ISO -> value for <input type="datetime-local"> (local time, no seconds). */
function isoToLocalInput(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

function localInputToIso(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

export function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const { t } = useTranslation();
  const [customOpen, setCustomOpen] = useState(value.label === "custom");
  const [start, setStart] = useState(isoToLocalInput(value.start));
  const [end, setEnd] = useState(isoToLocalInput(value.end));

  const presetKey = PRESETS.find((p) => p.key === value.label)?.key;
  const triggerLabel = customOpen
    ? t("dateRange.custom")
    : t(`dateRange.preset_${presetKey ?? "24h"}`);

  const applyPreset = (p: Preset) => {
    setCustomOpen(false);
    onChange(resolvePreset(p.hours, p.key));
  };

  const applyCustom = () => {
    onChange({
      start: localInputToIso(start),
      end: localInputToIso(end),
      label: "custom",
    });
  };

  return (
    <div className="flex items-center gap-2" data-testid="date-range-picker">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" data-testid="date-range-trigger">
            <CalendarRange className="h-4 w-4" />
            {triggerLabel}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-44">
          {PRESETS.map((p) => (
            <DropdownMenuItem
              key={p.key}
              onClick={() => applyPreset(p)}
              data-testid={`date-range-${p.key}`}
            >
              {!customOpen && value.label === p.key && <Check className="h-3.5 w-3.5" />}
              {t(`dateRange.preset_${p.key}`)}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => setCustomOpen(true)}
            data-testid="date-range-custom"
          >
            {customOpen && <Check className="h-3.5 w-3.5" />}
            {t("dateRange.custom")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {customOpen && (
        <div className="flex items-center gap-1.5" data-testid="date-range-custom-inputs">
          <Input
            type="datetime-local"
            className="h-8 w-44"
            value={start}
            onChange={(e) => setStart(e.target.value)}
            aria-label={t("dateRange.start")}
            data-testid="date-range-start"
          />
          <span className="text-muted-foreground">→</span>
          <Input
            type="datetime-local"
            className="h-8 w-44"
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            aria-label={t("dateRange.end")}
            data-testid="date-range-end"
          />
          <Button size="sm" variant="secondary" onClick={applyCustom} data-testid="date-range-apply">
            {t("dateRange.apply")}
          </Button>
        </div>
      )}
    </div>
  );
}
