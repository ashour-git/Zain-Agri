import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans_Arabic } from "next/font/google";
import type { ReactNode } from "react";

import { AuthProvider } from "@/lib/auth-provider";

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
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
