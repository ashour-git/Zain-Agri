import { Sprout } from "lucide-react";
import type { ReactNode } from "react";

import { AuthGuard } from "@/components/auth/auth-guard";
import { BrandMark, BrandWordmark } from "@/components/brand";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGuard redirectIfAuthenticated>
      <div className="relative min-h-dvh overflow-hidden bg-brand-950">
        <div
          className="pointer-events-none absolute -left-24 -top-24 size-[28rem] rounded-full bg-brand-700/40 blur-3xl"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -bottom-32 -right-16 size-[26rem] rounded-full bg-accent-500/10 blur-3xl"
          aria-hidden="true"
        />

        <div className="relative mx-auto flex min-h-dvh w-full max-w-6xl flex-col px-5 py-8 sm:px-8">
          <div className="flex items-center gap-3">
            <BrandMark />
            <BrandWordmark />
          </div>

          <div className="flex flex-1 items-center justify-center py-10">
            <div className="w-full max-w-md">{children}</div>
          </div>

          <p className="flex items-center justify-center gap-2 text-xs text-brand-300/70">
            <Sprout className="size-3.5" aria-hidden="true" />
            ZAIN AGRI - منصة إدارة الأعمال الزراعية
          </p>
        </div>
      </div>
    </AuthGuard>
  );
}
