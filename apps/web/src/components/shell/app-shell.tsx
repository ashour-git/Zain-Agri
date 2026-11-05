"use client";

import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { Header } from "@/components/shell/header";
import { Sidebar } from "@/components/shell/sidebar";
import { useAuth } from "@/lib/auth-provider";

const TITLES: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "نظرة عامة", subtitle: "ملخص أداء المتجر" },
  "/products": { title: "المنتجات", subtitle: "الكتالوج والأسعار ووحدات القياس" },
  "/inventory": { title: "المخزون", subtitle: "الأرصدة والحركات والدفعات" },
  "/settings/security": { title: "الأمان والجلسات", subtitle: "إدارة الدخول والأجهزة المرتبطة" },
};

export function AppShell({ children }: { children: ReactNode }) {
  const { session, signOut } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  const heading = TITLES[pathname] ?? { title: "ZAIN AGRI", subtitle: "منصة إدارة الأعمال الزراعية" };
  const workspaceName = session?.tenant?.name ?? "مساحة عمل";
  const initial = session?.user.full_name?.trim().charAt(0) || "ز";

  return (
    <div className="flex min-h-dvh">
      <Sidebar workspaceName={workspaceName} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header
          title={heading.title}
          subtitle={heading.subtitle}
          workspaceName={workspaceName}
          userInitial={initial}
          role={session?.role ?? null}
          onSignOut={() => {
            void signOut().then(() => router.replace("/login"));
          }}
        />
        <main className="flex-1">{children}</main>
        <footer className="border-t border-line px-5 py-4 text-xs text-ink-muted sm:px-8">
          ZAIN AGRI - Sprint 03. الجلسات محمية على الخادم، ولا تُخزَّن رموز الوصول في المتصفح.
        </footer>
      </div>
    </div>
  );
}
