import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const base =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md font-medium transition-colors duration-100 active:translate-y-px disabled:pointer-events-none disabled:opacity-50";

const variants: Record<Variant, string> = {
  primary: "bg-brand-700 text-white hover:bg-brand-800",
  secondary: "border border-line-strong bg-panel text-ink hover:border-brand-400 hover:bg-brand-50",
  ghost: "text-ink-muted hover:bg-brand-50 hover:text-brand-800",
  danger: "border border-line-strong bg-panel text-ink hover:border-red-300 hover:bg-red-50 hover:text-red-800",
};

const sizes: Record<Size, string> = {
  sm: "min-h-9 px-2.5 text-[13px]",
  md: "min-h-10 px-3.5 text-sm",
};

/** Class string for a button or a link styled as one. */
export function buttonClass(variant: Variant = "secondary", size: Size = "md", className?: string) {
  return cn(base, variants[variant], sizes[size], className);
}
