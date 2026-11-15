/** Credit customers «العملاء»: typed calls for the counter and the statement. */

import { apiRequest } from "@/lib/api";

export type Customer = {
  id: string;
  name: string;
  phone: string | null;
  active: boolean;
  /** Positive: the customer owes the shop. Negative: the shop owes them. */
  balance: string;
};

export type CustomerList = { items: Customer[]; total: number; page: number; page_size: number };

export type StatementKind = "opening" | "invoice" | "payment" | "return" | "correction";

export type StatementLine = {
  id: string;
  kind: StatementKind;
  amount: string;
  balance_after: string;
  note: string | null;
  reference_type: string | null;
  reference_id: string | null;
  created_at: string;
  created_by_name: string | null;
};

export type Statement = { customer: Customer; lines: StatementLine[]; balance: string };

const BASE = "/api/v1/customers";

export const KIND_LABELS: Record<StatementKind, string> = {
  opening: "رصيد سابق",
  invoice: "فاتورة آجل",
  payment: "تحصيل",
  return: "مرتجع",
  correction: "تصحيح",
};

export const listCustomers = (params: {
  q?: string;
  owes?: boolean;
  includeInactive?: boolean;
  page?: number;
  pageSize?: number;
}) => {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.pageSize ?? 50),
  });
  if (params.q) query.set("q", params.q);
  if (params.owes) query.set("owes", "true");
  if (params.includeInactive) query.set("include_inactive", "true");
  return apiRequest<CustomerList>(`${BASE}?${query.toString()}`);
};

export const createCustomer = (body: { name: string; phone?: string; opening_balance?: string }) =>
  apiRequest<Customer>(BASE, { method: "POST", body });

export const updateCustomer = (id: string, body: { name?: string; phone?: string | null; active?: boolean }) =>
  apiRequest<Customer>(`${BASE}/${id}`, { method: "PATCH", body });

export const getStatement = (id: string) => apiRequest<Statement>(`${BASE}/${id}/statement`);

export const recordPayment = (id: string, body: { amount: string; note?: string }) =>
  apiRequest<Customer>(`${BASE}/${id}/payments`, { method: "POST", body });

export const recordCorrection = (id: string, body: { amount: string; reason: string }) =>
  apiRequest<Customer>(`${BASE}/${id}/corrections`, { method: "POST", body });
