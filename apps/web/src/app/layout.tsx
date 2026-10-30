import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans_Arabic } from "next/font/google";
import type { ReactNode } from "react";

import { Sidebar } from "@/components/shell/sidebar";
import { Header } from "@/components/shell/header";

import "./globals.css";

const arabic = IBM_Plex_Sans_Arabic({
  subsets: ["arabic", "latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-arabic",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "ZAIN AGRI — منصة إدارة الأعمال الزراعية",
    template: "%s | ZAIN AGRI",
  },
  description:
    "منصة متكاملة لإدارة متاجر المستلزمات الزراعية: المخزون، نقطة البيع، الحسابات والتقارير.",
};

export const viewport: Viewport = {
  themeColor: "#04241a",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ar" dir="rtl" className={arabic.variable}>
      <body className="min-h-dvh font-sans antialiased">
        <div className="flex min-h-dvh">
          <Sidebar />
          <div className="flex min-w-0 flex-1 flex-col">
            <Header title="نظرة عامة" subtitle="ملخص أداء المتجر" />
            <main className="flex-1">{children}</main>
            <footer className="border-t border-line px-5 py-4 text-[11px] text-ink-muted sm:px-8">
              ZAIN AGRI — أساس Sprint 01. الأرقام ستظهر بعد ربط وحدات المخزون والمبيعات.
            </footer>
          </div>
        </div>
      </body>
    </html>
  );
}
