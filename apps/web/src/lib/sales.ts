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
 * Exact money for the counter screen. Floats round 0.5 x 4.35 to 2.17 while the
 * server's Decimal half-up gives 2.18, so amounts are fractions of BigInts and
 * rounded once to whole piastres (cents), exactly like the server.
 */
type Fraction = { num: bigint; den: bigint };

/** Arabic-Indic digits, the Arabic decimal mark and thousands separators → "1250.5". */
export function normalizeNumber(input: string): string {
  return input
    .replace(/[٠-٩]/g, (digit) => String(digit.charCodeAt(0) - 0x0660))
    .replace(/[۰-۹]/g, (digit) => String(digit.charCodeAt(0) - 0x06f0))
    .replace(/[٫]/g, ".")
    .replace(/[,٬\s]/g, "");
}

/** "12.345" → 12345/1000; null when it is not a plain non-negative number. */
export function parseDecimal(input: string): Fraction | null {
  const text = normalizeNumber(input);
  const match = /^(\d*)(?:\.(\d*))?$/.exec(text);
  const whole = match?.[1] ?? "";
  const fraction = match?.[2] ?? "";
  if (!match || whole + fraction === "") return null;
  return { num: BigInt(`${whole}${fraction}` || "0"), den: BigInt(10) ** BigInt(fraction.length) };
}

/** Product of fractions, rounded half-up to whole cents. */
export function centsOf(...parts: Fraction[]): bigint {
  let num = BigInt(100);
  let den = BigInt(1);
  for (const part of parts) {
    num *= part.num;
    den *= part.den;
  }
  return (num * BigInt(2) + den) / (den * BigInt(2));
}

/** Cents of a typed amount; null when it does not parse. Empty means 0. */
export function centsOfInput(input: string): bigint | null {
  if (input.trim() === "") return BigInt(0);
  const value = parseDecimal(input);
  return value ? centsOf(value) : null;
}

/** 123456n → "1234.56" */
export function centsToString(cents: bigint): string {
  const negative = cents < BigInt(0);
  const absolute = negative ? -cents : cents;
  const text = `${absolute / BigInt(100)}.${String(absolute % BigInt(100)).padStart(2, "0")}`;
  return negative ? `-${text}` : text;
}

/** How many base units one `unitId` holds, as an exact fraction (null if unknown). */
export function exactFactor(
  unitId: string,
  baseUnitId: string,
  conversions: { from_unit_id: string; to_unit_id: string; factor: string }[],
): Fraction | null {
  if (unitId === baseUnitId) return { num: BigInt(1), den: BigInt(1) };
  for (const conversion of conversions) {
    const factor = parseDecimal(conversion.factor);
    if (!factor || factor.num === BigInt(0)) continue;
    if (conversion.from_unit_id === unitId && conversion.to_unit_id === baseUnitId) return factor;
    if (conversion.from_unit_id === baseUnitId && conversion.to_unit_id === unitId) {
      return { num: factor.den, den: factor.num };
    }
  }
  return null;
}
