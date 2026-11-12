import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth/auth-guard";
import { ZainLogo } from "@/components/brand";
import { DeveloperCredit } from "@/components/developer-credit";

/* What the product does today, stated plainly. No promises about modules still being built. */
const FACTS = [
  {
    title: "تنبيه قبل النفاد",
    body: "يظهر الصنف في قائمة الطلب عند بلوغ حده الأدنى.",
  },
  {
    title: "سجل حركة لا يُمحى",
    body: "كل كمية دخلت أو خرجت محفوظة، ولا تُعدَّل أو تُحذف.",
  },
  {
    title: "صلاحية لكل دور",
    body: "المالك والمدير وأمين المخزن والكاشير، كلٌّ بصلاحياته.",
  },
];

/** The strip of grass along the bottom of the shop sign. */
function GrassEdge() {
  return (
    <svg
      viewBox="0 0 400 64"
      preserveAspectRatio="none"
      className="pointer-events-none absolute inset-x-0 bottom-0 h-20 w-full"
      aria-hidden="true"
    >
      <path
        fill="#9bcb2e"
        fillOpacity="0.5"
        d="M0 64V44L8 24L14 44L22 14L28 42L36 26L42 44L52 10L58 44L66 28L74 46L82 16L88 44L98 30L104 46L114 12L120 44L128 26L136 46L146 18L152 44L162 32L168 46L178 8L184 44L192 28L200 46L210 16L216 44L226 30L232 46L242 12L248 44L256 24L264 46L274 16L280 44L290 32L296 46L306 10L312 44L320 26L328 46L338 18L344 44L354 30L360 46L370 14L376 44L384 28L392 46L400 20V64Z"
      />
      <path fill="#0e4825" d="M0 64V54H400V64Z" />
    </svg>
  );
}

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard redirectIfAuthenticated>
      <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)] xl:grid-cols-[minmax(0,1fr)_minmax(0,36rem)]">
        <div className="flex flex-col px-5 py-8 sm:px-10">
          <ZainLogo className="w-44" />
          <div className="flex flex-1 items-center justify-center py-10">
            <div className="w-full max-w-sm">{children}</div>
          </div>
          <DeveloperCredit className="text-center" />
        </div>

        <aside className="relative hidden flex-col justify-between overflow-hidden bg-brand-800 px-12 pb-28 pt-12 text-white lg:flex">
          <div className="max-w-md">
            <h2 className="text-[28px] font-semibold leading-[1.45] text-balance">
              رصيد كل صنف في محلك، محسوب ومسجَّل.
            </h2>
            <p className="mt-4 max-w-[42ch] text-[15px] leading-relaxed text-brand-100">
              نظام لإدارة مخزون المتاجر الزراعية: البذور والأسمدة والمبيدات والمستلزمات.
            </p>

            <dl className="mt-10 divide-y divide-white/15 border-y border-white/15">
              {FACTS.map((fact) => (
                <div key={fact.title} className="py-4">
                  <dt className="text-[15px] font-semibold text-accent-300">{fact.title}</dt>
                  <dd className="mt-1.5 text-[14px] leading-relaxed text-brand-50">{fact.body}</dd>
                </div>
              ))}
            </dl>
          </div>

          <p className="text-[18px] font-semibold text-accent-300">مكسبنا الحقيقي هو ثقتك</p>
          <GrassEdge />
        </aside>
      </div>
    </AuthGuard>
  );
}
