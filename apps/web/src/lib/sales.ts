/** Sales: typed calls, money arithmetic for the counter, and the WhatsApp link. */

import { apiRequest } from "@/lib/api";

export type SaleLine = {
  id: string;
  product_id: string;
  name_ar: string;
  unit_id: string;
  unit_name_ar: string;
  quantity: string;
  base_quantity: string;
  unit_price: string;
  line_total: string;
  returned_quantity: string;
  batches: { batch_id: string; batch_number: string; base_quantity: string }[];
};

export type Sale = {
  id: string;
  number: number;
  customer: { id: string; name: string; phone: string | null } | null;
  lines: SaleLine[];
  subtotal: string;
  discount: string;
  total: string;
  paid: string;
  credit: string;
  returned_total: string;
  created_at: string;
  created_by_name: string | null;
  shared: boolean;
};

export type SaleSummary = {
  id: string;
  number: number;
  customer_name: string | null;
  total: string;
  credit: string;
  created_at: string;
  created_by_name: string | null;
};

export type SaleList = { items: SaleSummary[]; total: number; page: number; page_size: number };

export type SaleLineInput = {
  product_id: string;
  quantity: string;
  unit_id?: string;
  unit_price?: string;
};

export type SaleInput = {
  customer_id: string | null;
  lines: SaleLineInput[];
  discount: string;
  paid?: string;
  idempotency_key: string;
};

export type ReturnResult = {
  id: string;
  number: number;
  total: string;
  credit_reduction: string;
  cash_refund: string;
};

export type PublicInvoice = {
  shop_name: string;
  number: number;
  created_at: string;
  lines: { name_ar: string; unit_name_ar: string; quantity: string; unit_price: string; line_total: string }[];
  subtotal: string;
  discount: string;
  total: string;
  paid: string;
  remaining: string;
  returned_total: string;
};

const BASE = "/api/v1/sales";

export const createSale = (body: SaleInput) => apiRequest<Sale>(BASE, { method: "POST", body });

export const getSale = (id: string) => apiRequest<Sale>(`${BASE}/${id}`);

export const listSales = (params: { q?: string; customerId?: string; page?: number }) => {
  const query = new URLSearchParams({ page: String(params.page ?? 1), page_size: "25" });
  if (params.q) query.set("q", params.q);
  if (params.customerId) query.set("customer_id", params.customerId);
  return apiRequest<SaleList>(`${BASE}?${query.toString()}`);
};

export const createReturn = (
  id: string,
  body: { lines: { line_id: string; quantity: string }[]; reason: string },
) => apiRequest<ReturnResult>(`${BASE}/${id}/returns`, { method: "POST", body });

export const shareSale = (id: string) =>
  apiRequest<{ url: string }>(`${BASE}/${id}/share`, { method: "POST" });

export const revokeShare = (id: string) => apiRequest<void>(`${BASE}/${id}/share`, { method: "DELETE" });

export const getPublicInvoice = (token: string) =>
  apiRequest<PublicInvoice>(`/api/v1/public/invoices/${encodeURIComponent(token)}`, { anonymous: true });

/** One key per sale screen: a double tap or a retry returns the same invoice. */
export function newSaleKey(): string {
  return `sale-${crypto.randomUUID()}`;
}

/** Round half-up to cents, the way the server does (NUMERIC(14,2), ROUND_HALF_UP). */
export function roundMoney(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/** Plain western-digit amount for messages: 1,250 or 1,250.5 (no currency). */
export function plainAmount(value: string | number): string {
  const number = typeof value === "number" ? value : Number(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(
    Number.isFinite(number) ? number : 0,
  );
}

/** The WhatsApp message the spec fixes. "الباقي" only when something is left. */
export function invoiceMessage(
  shopName: string,
  sale: { number: number; total: string; paid: string; credit: string; returned_total: string },
  link: string,
): string {
  const parts = [
    `فاتورة رقم ${sale.number}`,
    `الإجمالي ${plainAmount(sale.total)} جنيه`,
    `المدفوع ${plainAmount(sale.paid)}`,
  ];
  // Returns come off the debt first: what is still owed is credit minus returns.
  const owed = roundMoney(Math.max(Number(sale.credit) - Number(sale.returned_total), 0));
  if (owed > 0) parts.push(`الباقي ${plainAmount(owed)}`);
  return `${shopName}: ${parts.join("، ")}.\nالتفاصيل: ${link}`;
}

/** wa.me link: the phone as digits only (no +), or no phone to let them pick. */
export function whatsappUrl(phone: string | null, text: string): string {
  const digits = (phone ?? "").replace(/\D/g, "");
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

export const PRINT_SIZE_KEY = "zain.printSize";
export type PrintSize = "a4" | "80mm";

export function readPrintSize(): PrintSize {
  try {
    return window.localStorage.getItem(PRINT_SIZE_KEY) === "80mm" ? "80mm" : "a4";
  } catch {
    return "a4";
  }
}

export function savePrintSize(size: PrintSize): void {
  try {
    window.localStorage.setItem(PRINT_SIZE_KEY, size);
  } catch {
    // Private mode: the choice just isn't remembered.
  }
}

/*
 * Sharing again issues a new token and kills the old link, so the link made on
 * this device is kept and reused: a resend never breaks what the customer has.
 */
const LINK_KEY = (id: string) => `zain.invoiceLink.${id}`;

export function rememberedLink(id: string): string | null {
  try {
    return window.localStorage.getItem(LINK_KEY(id));
  } catch {
    return null;
  }
}

export function rememberLink(id: string, url: string | null): void {
  try {
    if (url) window.localStorage.setItem(LINK_KEY(id), url);
    else window.localStorage.removeItem(LINK_KEY(id));
  } catch {
    // Not remembered: the next send makes a fresh link.
  }
}
