/** Stocktake (جرد): typed calls for the screens. */

import { apiRequest } from "@/lib/api";

export type StocktakeStatus = "open" | "applied" | "cancelled";
export type ShortageReason = "shortage" | "damage" | "expiry";

export type Stocktake = {
  id: string;
  name: string;
  scope: "all" | "category";
  category_id: string | null;
  blind: boolean;
  status: StocktakeStatus;
  created_at: string;
  applied_at: string | null;
  total_lines: number;
  counted_lines: number;
};

export type StocktakeLine = {
  line_id: string;
  product_id: string;
  sku: string;
  barcode: string | null;
  name_ar: string;
  batch_id: string | null;
  batch_number: string | null;
  base_unit_id: string;
  base_unit_name_ar: string;
  counted_quantity: string | null;
  counted_unit_id: string | null;
  counted_base_quantity: string | null;
  /** null while the count is blind and this line has not been counted yet */
  system_quantity: string | null;
  shortage_reason: ShortageReason;
};

export type LineList = { items: StocktakeLine[]; total: number; page: number; page_size: number };

export type ReviewItem = {
  line_id: string;
  product_id: string;
  name_ar: string;
  batch_number: string | null;
  base_unit_name_ar: string;
  system_quantity_at_count: string;
  counted_base_quantity: string;
  difference: string;
  current_quantity: string;
  shortage_reason: ShortageReason;
};

export type Review = {
  shortages: ReviewItem[];
  surpluses: ReviewItem[];
  unchanged: number;
  uncounted: { line_id: string; product_id: string; name_ar: string; batch_number: string | null }[];
};

const BASE = "/api/v1/stocktakes";

export const REASON_LABELS: Record<ShortageReason, string> = {
  shortage: "عجز",
  damage: "تالف",
  expiry: "منتهي الصلاحية",
};

export const STATUS_LABELS: Record<StocktakeStatus, string> = {
  open: "مفتوح",
  applied: "معتمد",
  cancelled: "ملغى",
};

export const listStocktakes = () => apiRequest<{ items: Stocktake[] }>(BASE);

export const startStocktake = (body: {
  scope: "all" | "category";
  category_id?: string;
  name?: string;
  blind: boolean;
}) => apiRequest<Stocktake>(BASE, { method: "POST", body });

export const getStocktake = (id: string) => apiRequest<Stocktake>(`${BASE}/${id}`);

export const getLines = (id: string, params: { q: string; onlyUncounted: boolean; page: number }) => {
  const query = new URLSearchParams({ page: String(params.page), page_size: "50" });
  if (params.q) query.set("q", params.q);
  if (params.onlyUncounted) query.set("only_uncounted", "true");
  return apiRequest<LineList>(`${BASE}/${id}/lines?${query.toString()}`);
};

export const countLine = (
  id: string,
  lineId: string,
  body: { quantity: string; unit_id?: string; shortage_reason?: ShortageReason },
) => apiRequest<StocktakeLine>(`${BASE}/${id}/lines/${lineId}`, { method: "PUT", body });

export const getReview = (id: string) => apiRequest<Review>(`${BASE}/${id}/review`);

export const applyStocktake = (id: string) =>
  apiRequest<{ corrections: number }>(`${BASE}/${id}/apply`, { method: "POST" });

export const cancelStocktake = (id: string) =>
  apiRequest<Stocktake>(`${BASE}/${id}/cancel`, { method: "POST" });
