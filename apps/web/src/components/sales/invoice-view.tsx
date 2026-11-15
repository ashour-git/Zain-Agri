import { BrandMark } from "@/components/brand";
import { formatDateTime, formatMoney, formatQuantity, toNumber } from "@/lib/catalog";
import type { PrintSize } from "@/lib/sales";
import { cn } from "@/lib/utils";

export type InvoiceData = {
  shopName: string;
  number: number;
  createdAt: string;
  customerName?: string | null;
  createdByName?: string | null;
  lines: {
    key: string;
    name_ar: string;
    unit_name_ar: string;
    quantity: string;
    unit_price: string;
    line_total: string;
    returned_quantity?: string;
  }[];
  subtotal: string;
  discount: string;
  total: string;
  paid: string;
  remaining: string;
  returnedTotal: string;
};

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4", strong && "text-base font-bold text-ink")}>
      <dt className={strong ? undefined : "text-ink-muted"}>{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * One invoice, as printed and as shown. A4 is a document with a line table;
 * 80 mm is one narrow column for a receipt printer. The page around it owns
 * the buttons, which are hidden when printing.
 */
export function InvoiceView({ invoice, size }: { invoice: InvoiceData; size: PrintSize }) {
  const narrow = size === "80mm";
  const hasDiscount = toNumber(invoice.discount) > 0;
  const hasReturns = toNumber(invoice.returnedTotal) > 0;
  // A return comes off the debt first, so returns always take min(returns, credit)
  // off what is owed on this invoice.
  const remaining = Math.max(toNumber(invoice.remaining) - toNumber(invoice.returnedTotal), 0);

  return (
    <article
      className={cn(
        "invoice-sheet mx-auto bg-white text-ink",
        narrow
          ? "receipt-80 w-full max-w-[20rem] space-y-3 border border-dashed border-line-strong px-4 py-5 text-[13px]"
          : "w-full max-w-3xl space-y-6 rounded-lg border border-line px-5 py-6 text-sm sm:px-8 sm:py-8",
      )}
      aria-label={`فاتورة رقم ${invoice.number}`}
    >
      <header className={cn("flex gap-3", narrow ? "flex-col items-center text-center" : "items-start justify-between")}>
        <div className={cn("flex items-center gap-3", narrow && "flex-col gap-1.5")}>
          <BrandMark className={narrow ? "size-9" : "size-11"} />
          <div>
            <p className={cn("font-bold text-ink", narrow ? "text-base" : "text-lg")}>{invoice.shopName}</p>
            <p className="text-xs text-ink-muted">فاتورة بيع</p>
          </div>
        </div>
        <dl className={cn("text-xs", narrow ? "space-y-0.5" : "space-y-1 text-end")}>
          <div>
            <dt className="inline text-ink-muted">رقم الفاتورة: </dt>
            <dd className="inline font-bold tabular-nums text-ink">{invoice.number}</dd>
          </div>
          <div>
            <dt className="inline text-ink-muted">التاريخ: </dt>
            <dd className="inline tabular-nums">{formatDateTime(invoice.createdAt)}</dd>
          </div>
          {invoice.customerName ? (
            <div>
              <dt className="inline text-ink-muted">العميل: </dt>
              <dd className="inline font-medium">{invoice.customerName}</dd>
            </div>
          ) : null}
        </dl>
      </header>

      {narrow ? (
        <ul className="divide-y divide-dashed divide-line-strong border-y border-dashed border-line-strong">
          {invoice.lines.map((line) => (
            <li key={line.key} className="space-y-0.5 py-2">
              <p className="font-medium">{line.name_ar}</p>
              <p className="flex justify-between gap-2 tabular-nums text-ink-muted">
                <span>
                  {formatQuantity(line.quantity)} {line.unit_name_ar} × {formatMoney(line.unit_price)}
                </span>
                <span className="font-medium text-ink">{formatMoney(line.line_total)}</span>
              </p>
              {toNumber(line.returned_quantity) > 0 ? (
                <p className="text-xs text-accent-700">مرتجع: {formatQuantity(line.returned_quantity)}</p>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px] sm:text-sm">
            <thead>
              <tr className="border-b border-line-strong text-xs text-ink-muted">
                <th scope="col" className="py-2 text-start font-medium">الصنف</th>
                <th scope="col" className="py-2 text-start font-medium">الكمية</th>
                <th scope="col" className="py-2 text-start font-medium">سعر الوحدة</th>
                <th scope="col" className="py-2 text-end font-medium">الإجمالي</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {invoice.lines.map((line) => (
                <tr key={line.key}>
                  <td className="py-2.5 pe-3 font-medium">
                    {line.name_ar}
                    {toNumber(line.returned_quantity) > 0 ? (
                      <span className="ms-2 text-xs font-normal text-accent-700">
                        (مرتجع {formatQuantity(line.returned_quantity)})
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2.5 pe-3 tabular-nums">
                    {formatQuantity(line.quantity)} {line.unit_name_ar}
                  </td>
                  <td className="py-2.5 pe-3 tabular-nums">{formatMoney(line.unit_price)}</td>
                  <td className="py-2.5 text-end tabular-nums">{formatMoney(line.line_total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <dl className={cn("space-y-1.5", !narrow && "ms-auto max-w-xs")}>
        {hasDiscount ? (
          <>
            <Row label="المجموع" value={formatMoney(invoice.subtotal)} />
            <Row label="الخصم" value={formatMoney(invoice.discount)} />
          </>
        ) : null}
        <Row label="الإجمالي" value={formatMoney(invoice.total)} strong />
        <Row label="المدفوع" value={formatMoney(invoice.paid)} />
        {hasReturns ? <Row label="مرتجعات" value={formatMoney(invoice.returnedTotal)} /> : null}
        {remaining > 0 ? (
          <Row label={hasReturns ? "الباقي (آجل) بعد المرتجع" : "الباقي (آجل)"} value={formatMoney(remaining.toFixed(2))} />
        ) : null}
      </dl>

      <footer className={cn("text-xs text-ink-muted", narrow ? "text-center" : "border-t border-line pt-4")}>
        شكرًا لتعاملكم معنا.
        {invoice.createdByName ? <span className="block">البائع: {invoice.createdByName}</span> : null}
      </footer>
    </article>
  );
}
