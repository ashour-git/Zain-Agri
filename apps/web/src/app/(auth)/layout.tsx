import { Check } from "lucide-react";
import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth/auth-guard";
import { BrandMark, BrandWordmark } from "@/components/brand";
import { DeveloperCredit } from "@/components/developer-credit";

/* What the product does today, stated plainly. No promises about modules still being built. */
const FACTS = [
  "تنبيه عند اقتراب أي صنف من حده الأدنى، قبل أن ينفد من الرف.",
  "سجل لكل كمية دخلت أو خرجت، لا يُمسح ولا يُعدَّل.",
  "صلاحيات منفصلة للمالك والمدير وأمين المخزن والكاشير.",
];

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard redirectIfAuthenticated>
      <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)] xl:grid-cols-[minmax(0,1fr)_minmax(0,34rem)]">
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

        <aside className="hidden flex-col justify-between bg-brand-800 px-10 py-12 text-white lg:flex">
          <div className="max-w-sm">
            <p className="text-[28px] font-semibold leading-snug">
              متجرك الزراعي كله، منظَّم في شاشة واحدة.
            </p>
            <ul className="mt-10 space-y-5">
              {FACTS.map((fact) => (
                <li key={fact} className="flex gap-3 text-[15px] leading-relaxed text-brand-50">
                  <Check className="mt-1 size-4 shrink-0 text-accent-300" aria-hidden="true" />
                  {fact}
                </li>
              ))}
            </ul>
          </div>
          <p className="text-sm text-brand-200">ZAIN AGRI</p>
        </aside>
      </div>
    </AuthGuard>
  );
}
