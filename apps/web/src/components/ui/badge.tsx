import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

type Variant = "brand" | "lime" | "neutral" | "warning" | "danger";

/*
 * Status, not decoration: a small dot plus the word. Colour alone never
 * carries the meaning, so the label always reads on its own.
 */
const variants: Record<Variant, { box: string; dot: string }> = {
  brand: { box: "bg-brand-50 text-brand-800", dot: "bg-brand-600" },
  lime: { box: "bg-brand-50 text-brand-800", dot: "bg-brand-500" },
  neutral: { box: "bg-surface text-ink-muted", dot: "bg-ink-muted/60" },
  warning: { box: "bg-accent-50 text-accent-700", dot: "bg-accent-500" },
  danger: { box: "bg-red-50 text-red-800", dot: "bg-red-600" },
};

export function Badge({
  className,
  variant = "neutral",
  children,
  ...props
}: ComponentProps<"span"> & { variant?: Variant }) {
  const style = variants[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium",
        style.box,
        className,
      )}
      {...props}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", style.dot)} aria-hidden="true" />
      {children}
    </span>
  );
}
