"use client";

import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { BackupFailureBanner } from "@/components/shell/backup-banner";
import { Header } from "@/components/shell/header";
import { Sidebar } from "@/components/shell/sidebar";
import { useAuth } from "@/lib/auth-provider";

const TITLES: Record<string, string> = {
  "/": "نظرة عامة",
  "/products": "المنتجات",
  "/inventory": "المخزون",
  "/audit": "سجل التعديلات",
  "/settings/security": "الحساب والأمان",
  "/settings/backup": "النسخة اليومية",
};

export function AppShell({ children }: { children: ReactNode }) {
  const { session, signOut } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const title = TITLES[pathname] ?? "ZAIN AGRI";
  const workspaceName = session?.tenant?.name ?? "متجر";
  const initial = session?.user.full_name?.trim().charAt(0) || "ز";

  return (
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded-md bg-brand-700 px-4 py-2 text-sm font-semibold text-white focus:not-sr-only focus:fixed focus:right-4 focus:top-4"
      >
        تخطَّ إلى المحتوى
      </a>
      <Sidebar workspaceName={workspaceName} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          title={title}
          workspaceName={workspaceName}
          userInitial={initial}
          userName={session?.user.full_name ?? "مستخدم"}
          role={session?.role ?? null}
          onSignOut={() => {
            void signOut().then(() => router.replace("/login"));
          }}
        />
        <BackupFailureBanner
          isOwner={session?.permissions.includes("tenant.settings.manage") ?? false}
        />
        <main id="main" tabIndex={-1} className="flex-1 outline-none">
          {children}
        </main>
      </div>
    </div>
  );
}
