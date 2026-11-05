import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "relative grid size-11 place-items-center rounded-2xl bg-gradient-to-br from-brand-500 to-brand-800 shadow-lg shadow-brand-950/30",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="size-6" fill="none" aria-hidden="true">
        <path
          d="M7 7.5h10L9 16.5h8"
          stroke="white"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span className="absolute -bottom-1 -left-1 size-3 rounded-full bg-accent-400 ring-2 ring-brand-950" />
    </div>
  );
}

export function BrandWordmark() {
  return (
    <div className="flex flex-col leading-tight">
      <span className="text-[15px] font-bold tracking-wide text-white">ZAIN AGRI</span>
      <span className="text-xs font-medium text-brand-200">منصة إدارة الأعمال الزراعية</span>
    </div>
  );
}
