import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleString();
}

/** Seconds -> compact Prometheus-style duration, e.g. 300 -> "5m", 3600 -> "1h". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return "0s";
  const units: [number, string][] = [
    [86400, "d"],
    [3600, "h"],
    [60, "m"],
    [1, "s"],
  ];
  const parts: string[] = [];
  let rem = Math.floor(seconds);
  for (const [size, suffix] of units) {
    if (rem >= size) {
      parts.push(`${Math.floor(rem / size)}${suffix}`);
      rem %= size;
    }
  }
  return parts.slice(0, 2).join(" ") || "0s";
}
