"use client";

import { CircleAlert, Printer } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { InvoiceView } from "@/components/sales/invoice-view";
import { buttonClass } from "@/components/ui/button";
import { Segmented, SkeletonRows } from "@/components/ui/data";
import { ApiRequestError } from "@/lib/api";
import { type PrintSize, type PublicInvoice, getPublicInvoice, readPrintSize, savePrintSize } from "@/lib/sales";

/** The invoice a customer opens from WhatsApp: no login, this one invoice only. */
export default function PublicInvoicePage() {
  const { token } = useParams<{ token: string }>();
  const [invoice, setInvoice] = useState<PublicInvoice | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [size, setSize] = useState<PrintSize>(readPrintSize);

  useEffect(() => {
    getPublicInvoice(token)
      .then(setInvoice)
      .catch((caught: unknown) =>
        setFailed(
          caught instanceof ApiRequestError
            ? caught.message
            : "تعذّر فتح الفاتورة. تحقق من الاتصال ثم أعد فتح الرابط.",
        ),
      );
  }, [token]);

  return (
    <main className="min-h-dvh bg-surface px-4 py-6 sm:px-8 sm:py-10">
      {failed ? (
        <div role="alert" className="mx-auto max-w-md space-y-3 rounded-lg border border-line bg-white px-5 py-8 text-center">
          <CircleAlert className="mx-auto size-7 text-red-700" aria-hidden="true" />
          <h1 className="text-lg font-semibold text-ink">لا يمكن فتح هذه الفاتورة</h1>
          <p className="text-sm leading-relaxed text-ink-muted">{failed}</p>
        </div>
      ) : !invoice ? (
        <div className="mx-auto max-w-3xl rounded-lg border border-line bg-white">
          <SkeletonRows rows={5} />
        </div>
      ) : (
        <div className="mx-auto max-w-3xl space-y-4">
          <div data-print-hide className="flex flex-wrap items-center justify-between gap-2">
            <button type="button" onClick={() => window.print()} className={buttonClass("secondary")}>
              <Printer className="size-4" aria-hidden="true" />
              طباعة أو حفظ PDF
            </button>
            <Segmented
              label="مقاس الطباعة"
              value={size}
              options={[
                { id: "a4", label: "A4" },
                { id: "80mm", label: "إيصال 80 مم" },
              ]}
              onChange={(value) => {
                setSize(value);
                savePrintSize(value);
              }}
            />
          </div>
          <InvoiceView
            size={size}
            invoice={{
              shopName: invoice.shop_name,
              number: invoice.number,
              createdAt: invoice.created_at,
              lines: invoice.lines.map((line, index) => ({ ...line, key: String(index) })),
              subtotal: invoice.subtotal,
              discount: invoice.discount,
              total: invoice.total,
              paid: invoice.paid,
              remaining: invoice.remaining,
              returnedTotal: invoice.returned_total,
            }}
          />
        </div>
      )}
    </main>
  );
}
