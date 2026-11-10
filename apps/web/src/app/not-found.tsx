import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex w-full max-w-lg flex-col items-center gap-4 px-5 py-20 text-center">
      <p className="text-5xl font-bold text-brand-700">404</p>
      <h2 className="text-lg font-bold text-ink">الصفحة غير موجودة</h2>
      <p className="text-sm text-ink-muted">الرابط الذي فتحته غير متاح أو تم نقله.</p>
      <Link
        href="/"
        className="rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-brand-800"
      >
        العودة إلى لوحة التحكم
      </Link>
    </div>
  );
}
