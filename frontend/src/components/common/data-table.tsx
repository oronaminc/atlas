import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/common/empty-state";
import { LoadingSpinner } from "@/components/common/loading-spinner";

export interface Column<T> {
  key: string;
  header: string;
  className?: string;
  render: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  loading?: boolean;
  emptyTitle?: string;
  search?: {
    value: string;
    onChange: (v: string) => void;
    placeholder?: string;
  };
  filters?: ReactNode;
  pagination?: {
    hasMore: boolean;
    onNext: () => void;
    onPrevious?: () => void;
    canGoPrevious?: boolean;
  };
  onRowClick?: (row: T) => void;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  loading,
  emptyTitle,
  search,
  filters,
  pagination,
  onRowClick,
}: DataTableProps<T>) {
  const { t } = useTranslation();

  return (
    <div className="space-y-4">
      {(search || filters) && (
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          {search && (
            <div className="relative w-full sm:max-w-xs">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search.value}
                onChange={(e) => search.onChange(e.target.value)}
                placeholder={search.placeholder ?? t("common.search")}
                className="pl-9"
              />
            </div>
          )}
          {filters}
        </div>
      )}

      <div className="rounded-md border">
        {loading ? (
          <LoadingSpinner />
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptyState title={emptyTitle ?? t("common.empty")} />
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map((col) => (
                  <TableHead key={col.key} className={col.className}>
                    {col.header}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={rowKey(row)}
                  className={onRowClick ? "cursor-pointer" : undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {columns.map((col) => (
                    <TableCell key={col.key} className={col.className}>
                      {col.render(row)}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {pagination && (
        <div className="flex items-center justify-end gap-2">
          {pagination.onPrevious && (
            <Button
              variant="outline"
              size="sm"
              onClick={pagination.onPrevious}
              disabled={!pagination.canGoPrevious}
            >
              <ChevronLeft className="h-4 w-4" />
              {t("common.previous")}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={pagination.onNext}
            disabled={!pagination.hasMore}
          >
            {t("common.next")}
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
