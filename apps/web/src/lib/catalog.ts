import type { MovementType, StockStatus } from "@/lib/types";

export const STOCK_LABELS: Record<StockStatus, string> = {
  out: "نفد",
  low: "تحت الحد",
  ok: "متوفر",
};

export const STOCK_BADGE_VARIANTS: Record<StockStatus, "danger" | "warning" | "lime"> = {
  out: "danger",
  low: "warning",
  ok: "lime",
};

export const MOVEMENT_LABELS: Record<MovementType, string> = {
  opening_balance: "رصيد افتتاحي",
  purchase: "توريد مشتريات",
  sale: "بيع",
  customer_return: "مرتجع عميل",
  supplier_return: "مرتجع مورد",
  adjustment_in: "تسوية بالزيادة",
  adjustment_out: "تسوية بالنقص",
  damage: "تالف",
  expiry: "منتهي الصلاحية",
  transfer_in: "تحويل وارد",
  transfer_out: "تحويل صادر",
};

export const WRITABLE_MOVEMENTS: MovementType[] = [
  "opening_balance",
  "adjustment_in",
  "adjustment_out",
];

const INBOUND = new Set<MovementType>([
  "opening_balance",
  "purchase",
  "customer_return",
  "adjustment_in",
  "transfer_in",
]);

export function isInbound(type: MovementType): boolean {
  return INBOUND.has(type);
}

/** Decimals are strings on the wire; parse only for display and arithmetic. */
export function toNumber(value: string | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

const quantityFormatter = new Intl.NumberFormat("ar-EG-u-nu-latn", {
  maximumFractionDigits: 4,
});

export function formatQuantity(value: string | null | undefined): string {
  return quantityFormatter.format(toNumber(value));
}

const moneyFormatter = new Intl.NumberFormat("ar-EG-u-nu-latn", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatMoney(value: string | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${moneyFormatter.format(toNumber(value))} ج.م`;
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ar-EG-u-nu-latn", { dateStyle: "medium" }).format(date);
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ar-EG-u-nu-latn", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

/**
 * Factor that turns `unitId` into the product's base unit.
 *
 * A conversion stores either "1 base = factor of unit" or "1 unit = factor of
 * base"; the caller passes the conversions of the product being edited.
 */
export function unitFactor(
  unitId: string,
  baseUnitId: string,
  conversions: { from_unit_id: string; to_unit_id: string; factor: string }[],
): number {
  if (unitId === baseUnitId) return 1;
  for (const conversion of conversions) {
    if (conversion.from_unit_id === unitId && conversion.to_unit_id === baseUnitId) {
      return toNumber(conversion.factor);
    }
    if (conversion.from_unit_id === baseUnitId && conversion.to_unit_id === unitId) {
      const factor = toNumber(conversion.factor);
      return factor > 0 ? 1 / factor : 0;
    }
  }
  return 0;
}
