"use client";

import { LinkIcon, MessageCircle, Plus, Printer, Undo2 } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { InvoiceView } from "@/components/sales/invoice-view";
import { ReturnDialog } from "@/components/sales/return-dialog";
import { buttonClass } from "@/components/ui/button";
import { LoadError, Segmented, SkeletonRows } from "@/components/ui/data";
import { FormError, FormNotice } from "@/components/ui/field";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatMoney, toNumber } from "@/lib/catalog";
import {
  type PrintSize,
  type ReturnResult,
  type Sale,
  getSale,
  invoiceMessage,
  readPrintSize,
  revokeShare,
  savePrintSize,
  shareSale,
  whatsappUrl,
} from "@/lib/sales";

/** Shown once after saving: the counter opens /sales/<id>?saved=1. */
function SavedNotice() {
  if (useSearchParams().get("saved") !== "1") return null;
  return <FormNotice>حُفظت الفاتورة. اطبعها أو أرسلها للعميل على واتساب.</FormNotice>;
}

function returnNotice(result: ReturnResult): string {
  const parts = [`سُجّل المرتجع رقم ${result.number} بقيمة ${formatMoney(result.total)}.`];
  if (toNumber(result.credit_reduction) > 0) parts.push(`خُصم من حساب العميل ${formatMoney(result.credit_reduction)}.`);
  if (toNumber(result.cash_refund) > 0) parts.push(`رُدّ للعميل نقدًا ${formatMoney(result.cash_refund)}.`);
  return parts.join(" ");
}

export default function InvoicePage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const canReturn = permissions.includes("sales.refund");
  const canRevoke = permissions.includes("sales.discount");
  const shopName = session?.tenant?.name ?? "المتجر";

  const [sale, setSale] = useState<Sale | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [size, setSize] = useState<PrintSize>(readPrintSize);
  const [returning, setReturning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    getSale(id)
      .then((result) => {
        setFailed(null);
        setSale(result);
      })
      .catch((caught: unknown) =>
        setFailed(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل الفاتورة."),
      );
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (failed) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <LoadError message={failed} onRetry={load} />
      </div>
    );
  }
  if (!sale) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <SkeletonRows rows={5} />
      </div>
    );
  }

  const onWhatsapp = async () => {
    setError(null);
    // Opened now, inside the tap, so the browser does not block it as a popup.
    const tab = window.open("about:blank", "_blank");
    setBusy(true);
    try {
      // The server returns the same link every time until it is revoked.
      const link = (await shareSale(sale.id)).url;
      if (!sale.shared) setSale({ ...sale, shared: true });
      const url = whatsappUrl(sale.customer?.phone ?? null, invoiceMessage(shopName, sale, link));
      if (tab) {
        tab.opener = null;
        tab.location.href = url;
      } else {
        window.location.href = url;
      }
    } catch (caught) {
      tab?.close();
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر تجهيز رابط الفاتورة.");
    } finally {
      setBusy(false);
    }
  };

  const onRevoke = async () => {
    setError(null);
    setBusy(true);
    try {
      await revokeShare(sale.id);
      setSale({ ...sale, shared: false });
      setNotice("أُوقف رابط الفاتورة. من معه الرابط القديم لن يفتح الفاتورة.");
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر إيقاف الرابط.");
    } finally {
      setBusy(false);
    }
  };

  const fullyReturned = sale.lines.every((line) => toNumber(line.returned_quantity) >= toNumber(line.quantity));

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-4 py-6 sm:px-8">
      <div data-print-hide className="space-y-3">
        {notice ? (
          <FormNotice>{notice}</FormNotice>
        ) : (
          <Suspense fallback={null}>
            <SavedNotice />
          </Suspense>
        )}
        <FormError>{error}</FormError>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => window.print()} className={buttonClass("primary")}>
            <Printer className="size-4" aria-hidden="true" />
            طباعة
          </button>
          <button type="button" onClick={() => void onWhatsapp()} disabled={busy} className={buttonClass("secondary")}>
            <MessageCircle className="size-4 text-brand-700" aria-hidden="true" />
            إرسال واتساب
          </button>
          {canReturn && !fullyReturned ? (
            <button type="button" onClick={() => setReturning(true)} className={buttonClass("secondary")}>
              <Undo2 className="size-4" aria-hidden="true" />
              مرتجع
            </button>
          ) : null}
          {canRevoke && sale.shared ? (
            <button type="button" onClick={() => void onRevoke()} disabled={busy} className={buttonClass("danger", "sm")}>
              <LinkIcon className="size-4" aria-hidden="true" />
              إيقاف رابط الفاتورة
            </button>
          ) : null}
          <div className="ms-auto flex items-center gap-2">
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
            <Link href="/sales" className={buttonClass("ghost", "sm")}>
              <Plus className="size-4" aria-hidden="true" />
              فاتورة جديدة
            </Link>
          </div>
        </div>
      </div>

      <InvoiceView
        size={size}
        invoice={{
          shopName,
          number: sale.number,
          createdAt: sale.created_at,
          customerName: sale.customer?.name ?? null,
          createdByName: sale.created_by_name,
          lines: sale.lines.map((line) => ({ ...line, key: line.id })),
          subtotal: sale.subtotal,
          discount: sale.discount,
          total: sale.total,
          paid: sale.paid,
          remaining: sale.credit,
          returnedTotal: sale.returned_total,
        }}
      />

      {canReturn ? (
        <ReturnDialog
          sale={sale}
          open={returning}
          onClose={() => setReturning(false)}
          onDone={(result) => {
            setReturning(false);
            setNotice(returnNotice(result));
            load();
          }}
        />
      ) : null}
    </div>
  );
}
