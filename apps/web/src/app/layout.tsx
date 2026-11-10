import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth-provider";

// Self-hosted: the font ships with the app and never depends on reaching Google at runtime.
import "@fontsource-variable/readex-pro";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "ZAIN AGRI - منصة إدارة الأعمال الزراعية",
    template: "%s | ZAIN AGRI",
  },
  description:
    "منصة متكاملة لإدارة متاجر المستلزمات الزراعية: المخزون، نقطة البيع، الحسابات والتقارير.",
};

export const viewport: Viewport = {
  themeColor: "#f6f7f4",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ar" dir="rtl">
      <body className="min-h-dvh font-sans antialiased">
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
