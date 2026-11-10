import { STOCK_LABELS, formatQuantity, toNumber } from "@/lib/catalog";
import type { StockStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const FILL: Record<StockStatus, string> = {
  ok: "bg-brand-600",
  low: "bg-accent-500",
  out: "bg-red-600",
};

const TEXT: Record<StockStatus, string> = {
  ok: "text-ink",
  low: "text-accent-700",
  out: "text-red-700",
};

/**
 * How full the shelf is, read at a glance: the bar spans twice the reorder
 * level, so the tick in the middle is the minimum and a healthy product sits
 * past it. With no minimum set, any stock reads as full.
 */
export function StockGauge({
  quantity,
  minimum,
  status,
  unit,
  className,
}: {
  quantity: string;
  minimum: string;
  status: StockStatus;
  unit?: string;
  className?: string;
}) {
  const qty = toNumber(quantity);
  const min = toNumber(minimum);
  const ratio = min > 0 ? Math.min(qty / (min * 2), 1) : qty > 0 ? 1 : 0;

  return (
    <div className={cn("min-w-28", className)}>
      <div className="flex items-baseline gap-1.5">
        <span className={cn("tabular text-sm font-semibold", TEXT[status])}>{formatQuantity(quantity)}</span>
        {unit ? <span className="text-xs text-ink-muted">{unit}</span> : null}
        {status !== "ok" ? (
          <span className={cn("ms-auto text-xs font-medium", TEXT[status])}>{STOCK_LABELS[status]}</span>
        ) : null}
      </div>
      <div
        className="relative mt-1.5 h-1.5 overflow-hidden rounded-full bg-line"
        role="img"
        aria-label={`${STOCK_LABELS[status]}: ${formatQuantity(quantity)}${min > 0 ? ` من حد أدنى ${formatQuantity(minimum)}` : ""}`}
      >
        <div className={cn("h-full rounded-full", FILL[status])} style={{ width: `${ratio * 100}%` }} />
        {min > 0 ? (
          <span className="absolute inset-y-0 start-1/2 w-px bg-ink/40" aria-hidden="true" />
        ) : null}
      </div>
    </div>
  );
}
