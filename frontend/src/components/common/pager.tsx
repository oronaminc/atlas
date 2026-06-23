import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

interface PagerProps {
  page: number;
  pages: number;
  total?: number;
  onPage: (page: number) => void;
  /** how many numbered buttons to show at most */
  maxButtons?: number;
}

/** Numbered 1..N pager with prev/next, used for `?page=&page_size=` endpoints. */
export function Pager({ page, pages, total, onPage, maxButtons = 10 }: PagerProps) {
  const { t } = useTranslation();
  if (pages <= 1) {
    return total !== undefined ? (
      <div className="flex justify-end text-xs text-muted-foreground">
        {t("common.totalCount", { count: total })}
      </div>
    ) : null;
  }

  // Window the visible page buttons around the current page, capped at maxButtons.
  const half = Math.floor(maxButtons / 2);
  let start = Math.max(1, page - half);
  const end = Math.min(pages, start + maxButtons - 1);
  start = Math.max(1, end - maxButtons + 1);
  const visible: number[] = [];
  for (let p = start; p <= end; p += 1) visible.push(p);

  return (
    <div className="flex flex-wrap items-center justify-end gap-1">
      {total !== undefined && (
        <span className="mr-2 text-xs text-muted-foreground">
          {t("common.totalCount", { count: total })}
        </span>
      )}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPage(page - 1)}
        disabled={page <= 1}
      >
        <ChevronLeft className="h-4 w-4" />
        {t("common.previous")}
      </Button>
      {visible.map((p) => (
        <Button
          key={p}
          variant={p === page ? "default" : "outline"}
          size="sm"
          className="min-w-9"
          onClick={() => onPage(p)}
        >
          {p}
        </Button>
      ))}
      <Button
        variant="outline"
        size="sm"
        onClick={() => onPage(page + 1)}
        disabled={page >= pages}
      >
        {t("common.next")}
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}
