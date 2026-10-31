import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Field({
  label,
  error,
  hint,
  className,
  id,
  ...props
}: ComponentProps<"input"> & { label: string; error?: string; hint?: string }) {
  const inputId = id ?? props.name;
  const describedBy = error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={inputId} className="block text-xs font-medium text-ink">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          "w-full rounded-xl border bg-white px-3.5 py-2.5 text-sm text-ink shadow-sm outline-none transition",
          "placeholder:text-ink-muted/60 focus:border-brand-500 focus:ring-2 focus:ring-brand-200",
          error ? "border-red-300 focus:border-red-400 focus:ring-red-100" : "border-line",
          className,
        )}
        {...props}
      />
      {error ? (
        <p id={`${inputId}-error`} className="text-[11px] text-red-600">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-[11px] text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function SubmitButton({
  children,
  pending,
  className,
  ...props
}: ComponentProps<"button"> & { pending?: boolean }) {
  return (
    <button
      className={cn(
        "inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-700 px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition",
        "hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...props}
      disabled={props.disabled || pending}
    >
      {pending ? (
        <span
          className="size-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
          aria-hidden="true"
        />
      ) : null}
      {children}
    </button>
  );
}

export function FormError({ children }: { children?: string | null }) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className="rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-xs leading-relaxed text-red-700"
    >
      {children}
    </div>
  );
}

export function FormNotice({ children }: { children?: string | null }) {
  if (!children) return null;
  return (
    <div
      role="status"
      className="rounded-xl border border-brand-200 bg-brand-50 px-3.5 py-2.5 text-xs leading-relaxed text-brand-800"
    >
      {children}
    </div>
  );
}
