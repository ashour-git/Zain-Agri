import { BrandMark, BrandWordmark } from "@/components/brand";

function Bar({ className }: { className: string }) {
  return <span className={`block rounded bg-line/70 ${className}`} />;
}

/**
 * The app's frame, drawn while the session is being checked, so the first
 * thing on screen is the real layout instead of a blank page with a spinner.
 * Holds no shop data: it is safe to show before we know who is visiting.
 */
export function ShellSkeleton() {
  return (
    <div className="flex min-h-dvh" role="status" aria-live="polite">
      <span className="sr-only">جارٍ فتح متجرك…</span>
      <aside
        aria-hidden="true"
        className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-e border-line bg-panel lg:flex"
      >
        <div className="flex items-center gap-3 px-6 pb-5 pt-6">
          <BrandMark />
          <BrandWordmark />
        </div>
        <div className="mx-3 mb-4 h-[58px] rounded-md border border-line" />
        <div className="space-y-5 px-6 pt-2 motion-safe:animate-pulse">
          <Bar className="h-3 w-12" />
          <Bar className="h-4 w-28" />
          <Bar className="h-4 w-24" />
          <Bar className="h-4 w-24" />
          <Bar className="mt-8 h-3 w-12" />
          <Bar className="h-4 w-32" />
          <Bar className="h-4 w-28" />
        </div>
      </aside>

      <div aria-hidden="true" className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-16 items-center gap-3 border-b border-line px-4 sm:px-8">
          <Bar className="h-5 w-32 motion-safe:animate-pulse" />
        </div>
        <div className="space-y-6 px-4 py-6 sm:px-8 motion-safe:animate-pulse">
          <div className="flex items-center justify-between gap-4">
            <Bar className="h-4 w-48" />
            <Bar className="h-9 w-28" />
          </div>
          <div className="h-32 rounded-lg border border-line bg-panel" />
          <div className="h-64 rounded-lg border border-line bg-panel" />
        </div>
      </div>
    </div>
  );
}
