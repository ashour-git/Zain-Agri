export default function Loading() {
  return (
    <div className="mx-auto w-full max-w-6xl space-y-8 px-5 py-8 sm:px-8" aria-busy="true">
      <div className="h-40 animate-pulse rounded-2xl bg-brand-900/10" />
      <div className="space-y-4">
        <div className="h-4 w-32 animate-pulse rounded bg-line" />
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-32 animate-pulse rounded-2xl border border-line bg-white" />
          ))}
        </div>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <div key={index} className="h-44 animate-pulse rounded-2xl border border-line bg-white" />
        ))}
      </div>
      <span className="sr-only">جارٍ التحميل…</span>
    </div>
  );
}
