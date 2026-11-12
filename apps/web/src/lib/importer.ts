/** Smart import of products: typed calls for the import screen. */

import { apiRequest } from "@/lib/api";

export type ImportField =
  | "name_ar"
  | "sku"
  | "barcode"
  | "unit"
  | "category"
  | "brand"
  | "sale_price"
  | "cost_price"
  | "minimum_stock"
  | "quantity";

export const FIELD_LABELS: Record<ImportField, string> = {
  name_ar: "اسم الصنف",
  sku: "كود الصنف",
  barcode: "الباركود",
  unit: "الوحدة",
  category: "التصنيف",
  brand: "الشركة",
  sale_price: "سعر البيع",
  cost_price: "سعر الشراء",
  minimum_stock: "الحد الأدنى",
  quantity: "الكمية الحالية",
};

export const FIELD_ORDER = Object.keys(FIELD_LABELS) as ImportField[];

export type AnalyzedColumn = {
  index: number;
  header: string;
  samples: string[];
  field: ImportField | null;
  source: "rules" | "ai" | null;
};

export type Analysis = {
  sheet_names: string[];
  sheet: string;
  header_row: number;
  first_data_row: number;
  columns: AnalyzedColumn[];
  rows: string[][];
  assistant_available: boolean;
  assistant_used: boolean;
};

export type ImportOptions = {
  default_unit_id: string | null;
  create_categories: boolean;
  create_brands: boolean;
  skip_errors: boolean;
};

export type PreviewRow = {
  row_number: number;
  status: "create" | "skip" | "error";
  reason_ar: string | null;
  warnings: string[];
  name_ar: string | null;
  sku: string | null;
  unit_name_ar: string | null;
  quantity: string | null;
  sale_price: string | null;
};

export type Preview = {
  counts: { create: number; skip: number; error: number };
  ignored_blank: number;
  rows: PreviewRow[];
  new_categories: string[];
  new_brands: string[];
  notices: string[];
};

export type CommitResult = {
  created: number;
  skipped: number;
  opening_balances: number;
  new_categories: number;
  new_brands: number;
};

const BASE = "/api/v1/imports";

export function analyzeFile(file: File, sheet?: string): Promise<Analysis> {
  const query = new URLSearchParams({ filename: file.name });
  if (sheet) query.set("sheet", sheet);
  return apiRequest<Analysis>(`${BASE}/analyze?${query.toString()}`, {
    method: "POST",
    rawBody: file,
  });
}

function requestBody(
  analysis: Analysis,
  mapping: Record<number, ImportField | "">,
  options: ImportOptions,
) {
  const clean: Record<string, ImportField> = {};
  for (const [index, field] of Object.entries(mapping)) {
    if (field) clean[index] = field;
  }
  return {
    mapping: clean,
    rows: analysis.rows,
    first_row_number: analysis.first_data_row,
    ...options,
  };
}

export const previewImport = (
  analysis: Analysis,
  mapping: Record<number, ImportField | "">,
  options: ImportOptions,
) => apiRequest<Preview>(`${BASE}/preview`, { method: "POST", body: requestBody(analysis, mapping, options) });

export const commitImport = (
  analysis: Analysis,
  mapping: Record<number, ImportField | "">,
  options: ImportOptions,
) => apiRequest<CommitResult>(`${BASE}/commit`, { method: "POST", body: requestBody(analysis, mapping, options) });

export async function downloadTemplate(): Promise<void> {
  const file = await apiRequest<Blob>(`${BASE}/template`, { blob: true });
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = "zain-products-template.xlsx";
  link.click();
  URL.revokeObjectURL(url);
}
