import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

type Variant = "brand" | "lime" | "neutral";

const variants: Record<Variant, string> = {
  brand: "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200",
  lime: "bg-accent-300/25 text-accent-600 ring-1 ring-inset ring-accent-400/50",
  neutral: "bg-surface text-ink-muted ring-1 ring-inset ring-line",
};

export function Badge({
  className,
  variant = "neutral",
  ...props
}: ComponentProps<"span"> & { variant?: Variant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}
