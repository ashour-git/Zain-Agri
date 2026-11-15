import type { Metadata } from "next";
import type { ReactNode } from "react";

// A customer's invoice link must never show up in search results.
export const metadata: Metadata = {
  title: "فاتورة",
  robots: { index: false, follow: false },
};

export default function PublicInvoiceLayout({ children }: { children: ReactNode }) {
  return children;
}
