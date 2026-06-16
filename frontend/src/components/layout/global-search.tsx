/** Top-bar global search (Feature B). Debounced; queries GET /search with a
 *  type toggle (host/label/text); results dropdown routes host -> /graph and
 *  label/incident -> /ops. Tenancy is server-side (choke point) — this is a
 *  thin client over the same endpoint every authenticated page shows. */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type {
  HostSearchResult,
  LabelSearchResult,
  SearchResponse,
  TextSearchResult,
} from "@/types";

type SearchType = "host" | "label" | "text";

export function GlobalSearch() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [type, setType] = useState<SearchType>("host");
  const [raw, setRaw] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);

  // debounce the input
  useEffect(() => {
    const id = setTimeout(() => setQ(raw.trim()), 250);
    return () => clearTimeout(id);
  }, [raw]);

  // close on outside click
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  const search = useQuery({
    queryKey: ["search", type, q],
    queryFn: () => api.get<SearchResponse>("/search", { q, type }),
    enabled: q.length >= 2,
  });

  const results = search.data?.data.results ?? [];

  const go = (path: string) => {
    setOpen(false);
    setRaw("");
    navigate(path);
  };

  return (
    <div ref={boxRef} className="relative w-full max-w-md" data-testid="global-search">
      <div className="flex items-center gap-1">
        <div className="relative flex-1">
          <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input
            className="h-9 pl-8"
            placeholder={t("search.placeholder")}
            value={raw}
            onFocus={() => setOpen(true)}
            onChange={(e) => {
              setRaw(e.target.value);
              setOpen(true);
            }}
            data-testid="search-input"
          />
        </div>
        <Select value={type} onValueChange={(v) => setType(v as SearchType)}>
          <SelectTrigger className="h-9 w-[5.5rem] text-xs" data-testid="search-type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="host" data-testid="search-type-host">
              {t("search.host")}
            </SelectItem>
            <SelectItem value="label" data-testid="search-type-label">
              {t("search.label")}
            </SelectItem>
            <SelectItem value="text" data-testid="search-type-text">
              {t("search.text")}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      {open && q.length >= 2 && (
        <div
          className="absolute z-50 mt-1 max-h-96 w-full overflow-y-auto rounded-md border bg-popover p-1 shadow-md"
          data-testid="search-results"
        >
          {search.isLoading && <div className="p-2 text-sm text-muted-foreground">…</div>}
          {!search.isLoading && results.length === 0 && (
            <div className="p-2 text-sm text-muted-foreground">{t("search.noResults")}</div>
          )}
          {type === "host" &&
            (results as HostSearchResult[]).map((r) => (
              <button
                key={r.host}
                className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => go("/graph")}
                data-testid="search-result-host"
              >
                <span className="font-mono">{r.host}</span>
                <span className="text-xs text-muted-foreground">{r.incidents} incidents</span>
              </button>
            ))}
          {type === "label" &&
            (results as LabelSearchResult[]).map((r) => (
              <button
                key={r.alert_event_id}
                className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => r.incident_id && go(`/ops?incident=${r.incident_id}`)}
                data-testid="search-result-label"
              >
                <span className="font-medium">{r.name}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {Object.entries(r.labels)
                    .map(([k, v]) => `${k}=${v}`)
                    .join(" ")
                    .slice(0, 40)}
                </span>
              </button>
            ))}
          {type === "text" &&
            (results as TextSearchResult[]).map((r) => (
              <button
                key={r.incident_id}
                className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                onClick={() => go(`/ops?incident=${r.incident_id}`)}
                data-testid="search-result-text"
              >
                <span className="truncate font-medium">{r.title}</span>
                <span className="ml-2 text-xs text-muted-foreground">{r.status}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
