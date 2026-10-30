"use client";

import { RotateCcw } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto flex w-full max-w-lg flex-col items-center gap-4 px-5 py-20 text-center">
      <h2 className="text-lg font-bold text-ink">حدث خطأ غير متوقع</h2>
      <p className="text-sm leading-relaxed text-ink-muted">
        تعذّر تحميل هذه الصفحة. يمكنك المحاولة مرة أخرى، وإذا تكرر الخطأ فأبلغ فريق التشغيل
        مع الرمز التالي.
      </p>
      {error.digest ? (
        <code className="rounded-md bg-white px-2 py-1 text-[11px] text-ink-muted ring-1 ring-line">
          {error.digest}
        </code>
      ) : null}
      <button
        type="button"
        onClick={reset}
        className="inline-flex items-center gap-2 rounded-xl bg-brand-700 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-800"
      >
        <RotateCcw className="size-4" aria-hidden="true" />
        إعادة المحاولة
      </button>
    </div>
  );
}
