import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth/auth-guard";
import { BrandMark, BrandWordmark } from "@/components/brand";
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

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard redirectIfAuthenticated>
      <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)] xl:grid-cols-[minmax(0,1fr)_minmax(0,36rem)]">
        <div className="flex flex-col px-5 py-8 sm:px-10">
          <div className="flex items-center gap-3">
            <BrandMark />
            <BrandWordmark />
          </div>
          <div className="flex flex-1 items-center justify-center py-10">
            <div className="w-full max-w-sm">{children}</div>
          </div>
          <DeveloperCredit className="text-center" />
        </div>

        <aside className="hidden flex-col justify-between bg-brand-800 px-12 py-12 text-white lg:flex">
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

          <p dir="ltr" lang="en" className="text-end text-[13px] font-medium tracking-wide text-brand-200">
            ZAIN AGRI
          </p>
        </aside>
      </div>
    </AuthGuard>
  );
}
