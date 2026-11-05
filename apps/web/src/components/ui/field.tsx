import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export const controlClass = cn(
  "w-full rounded-xl border border-line bg-white px-3.5 py-2.5 text-sm text-ink shadow-sm outline-none transition",
  "placeholder:text-ink-muted/60 focus:border-brand-500 focus:ring-2 focus:ring-brand-200",
);

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
        className={cn(controlClass, error && "border-red-300 focus:border-red-400 focus:ring-red-100", className)}
        {...props}
      />
      {error ? (
        <p id={`${inputId}-error`} className="text-xs text-red-600">
          {error}
        </p>
      ) : hint ? (
        <p id={`${inputId}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function SelectField({
  label,
  error,
  hint,
  className,
  children,
  ...props
}: ComponentProps<"select"> & { label: string; error?: string; hint?: string }) {
  const selectId = props.id ?? props.name;
  const describedBy = error ? `${selectId}-error` : hint ? `${selectId}-hint` : undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={selectId} className="block text-xs font-medium text-ink">
        {label}
      </label>
      <select
        id={selectId}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(controlClass, "appearance-none", error && "border-red-300", className)}
        {...props}
      >
        {children}
      </select>
      {error ? (
        <p id={`${selectId}-error`} className="text-xs text-red-600">
          {error}
        </p>
      ) : hint ? (
        <p id={`${selectId}-hint`} className="text-xs text-ink-muted">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function TextareaField({
  label,
  hint,
  className,
  ...props
}: ComponentProps<"textarea"> & { label: string; hint?: string }) {
  const textareaId = props.id ?? props.name;

  return (
    <div className="space-y-1.5">
      <label htmlFor={textareaId} className="block text-xs font-medium text-ink">
        {label}
      </label>
      <textarea
        id={textareaId}
        className={cn(controlClass, "min-h-20 resize-y", className)}
        {...props}
      />
      {hint ? <p className="text-xs text-ink-muted">{hint}</p> : null}
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
