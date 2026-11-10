import { cn } from "@/lib/utils";

/** One leaf with its vein, in the field green: the trade, legible at 32px. No gradient, no glow. */
export function BrandMark({ className, inverted }: { className?: string; inverted?: boolean }) {
  return (
    <span
      className={cn(
        "grid size-10 shrink-0 place-items-center rounded-md",
        inverted ? "bg-white text-brand-700" : "bg-brand-700 text-white",
        className,
      )}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" className="size-[60%]" fill="none">
        <path d="M5 19C5 10.5 10.5 5 19 5c0 8.5-5.5 14-14 14Z" fill="currentColor" />
        <path
          d="M5 19 13.5 10.5"
          stroke={inverted ? "var(--color-panel)" : "var(--color-brand-700)"}
          strokeWidth="1.8"
          strokeLinecap="round"
        />
      </svg>
    </span>
  );
}

export function BrandWordmark({ tone = "dark" }: { tone?: "dark" | "light" }) {
  return (
    <span className="flex flex-col leading-tight">
      <span
        className={cn("text-base font-semibold", tone === "dark" ? "text-ink" : "text-white")}
        dir="ltr"
        lang="en"
      >
        ZAIN AGRI
      </span>
      <span className={cn("text-xs", tone === "dark" ? "text-ink-muted" : "text-brand-100")}>
        إدارة المتجر الزراعي
      </span>
    </span>
  );
}
