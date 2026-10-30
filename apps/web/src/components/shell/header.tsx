import { BrandMark } from "@/components/brand";

export function Header({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur">
      <div className="flex items-center gap-4 px-5 py-4 sm:px-8">
        <div className="lg:hidden">
          <BrandMark className="size-9" />
        </div>

        <div className="min-w-0">
          <h1 className="truncate text-lg font-bold text-ink sm:text-xl">{title}</h1>
          {subtitle ? <p className="truncate text-xs text-ink-muted">{subtitle}</p> : null}
        </div>

        <div className="ms-auto flex items-center gap-3">
          <span className="hidden items-center gap-2 rounded-full border border-line bg-white px-3 py-1.5 sm:inline-flex">
            <span className="size-1.5 rounded-full bg-accent-500" aria-hidden="true" />
            <span className="text-[11px] text-ink-muted">مساحة عمل جديدة</span>
          </span>
          <div
            className="grid size-9 place-items-center rounded-full bg-brand-900 text-xs font-bold text-white"
            title="المستخدم الحالي"
          >
            ز
          </div>
        </div>
      </div>
    </header>
  );
}
