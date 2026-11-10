"use client";

import { RefreshCw, Search, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import { buttonClass } from "@/components/ui/button";
import { formatQuantity } from "@/lib/catalog";
import { cn } from "@/lib/utils";

/** Read a query-string value once, on first render (pages render client-side only). */
export function initialParam(name: string): string {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get(name) ?? "";
}

export const selectClass =
  "min-h-10 rounded-md border border-line-strong bg-panel px-3 text-sm text-ink outline-none transition-colors hover:border-brand-300 focus:border-brand-600 focus:ring-2 focus:ring-brand-100";

export function SearchBox({
  value,
  onChange,
  onSubmit,
  label,
  placeholder,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  label: string;
  placeholder: string;
}) {
  return (
    <form
      role="search"
      className="relative min-w-0 flex-1 basis-64"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Search
        className="pointer-events-none absolute inset-y-0 start-3 my-auto size-4 text-ink-muted"
        aria-hidden="true"
      />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-label={label}
        enterKeyHint="search"
        className={cn(selectClass, "w-full ps-9")}
      />
    </form>
  );
}

/** A small set of mutually exclusive filters shown as one joined control. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex min-h-10 overflow-x-auto rounded-md border border-line-strong bg-panel p-0.5"
    >
      {options.map((option) => {
        const selected = option.id === value;
        return (
          <button
            key={option.id || "all"}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(option.id)}
            className={cn(
              "whitespace-nowrap rounded-[4px] px-3 text-sm transition-colors",
              selected ? "bg-brand-700 font-medium text-white" : "text-ink-muted hover:bg-brand-50 hover:text-ink",
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export function Pagination({
  page,
  totalPages,
  total,
  noun,
  disabled,
  onChange,
}: {
  page: number;
  totalPages: number;
  total?: number;
  noun: string;
  disabled?: boolean;
  onChange: (page: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-sm text-ink-muted sm:px-5">
      <span className="tabular">
        {total !== undefined ? `${formatQuantity(String(total))} ${noun}` : null}
        {totalPages > 1 ? ` · صفحة ${page} من ${totalPages}` : null}
      </span>
      {totalPages > 1 ? (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onChange(Math.max(1, page - 1))}
            disabled={page <= 1 || disabled}
            className={buttonClass("secondary", "sm")}
          >
            السابق
          </button>
          <button
            type="button"
            onClick={() => onChange(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages || disabled}
            className={buttonClass("secondary", "sm")}
          >
            التالي
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
}: {
  icon: LucideIcon;
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="mx-auto flex max-w-sm flex-col items-center gap-3 px-5 py-14 text-center">
      <Icon className="size-6 text-ink-muted/70" aria-hidden="true" />
      <div className="space-y-1">
        <p className="text-[15px] font-medium text-ink">{title}</p>
        <p className="text-sm leading-relaxed text-ink-muted">{body}</p>
      </div>
      {action}
    </div>
  );
}

export function LoadError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3"
    >
      <p className="min-w-0 flex-1 text-sm text-red-800">{message}</p>
      <button type="button" onClick={onRetry} className={buttonClass("secondary", "sm")}>
        <RefreshCw className="size-4" aria-hidden="true" />
        إعادة المحاولة
      </button>
    </div>
  );
}

export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div aria-busy="true">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-4 border-b border-line px-5 py-4 last:border-b-0">
          <div className="h-3.5 w-1/3 animate-pulse rounded bg-line" />
          <div className="h-3.5 w-1/6 animate-pulse rounded bg-line" />
          <div className="ms-auto h-3.5 w-24 animate-pulse rounded bg-line" />
        </div>
      ))}
      <span className="sr-only">جارٍ التحميل…</span>
    </div>
  );
}

/** Column header cell for the shared data tables. */
export function Th({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <th scope="col" className={cn("px-4 py-2.5 text-start text-[13px] font-medium text-ink-muted first:ps-5", className)}>
      {children}
    </th>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return <td className={cn("px-4 py-3 align-middle first:ps-5", className)}>{children}</td>;
}
