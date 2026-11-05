"use client";

import {
  ChevronDown,
  ChevronUp,
  Layers,
  Loader2,
  PackageSearch,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { AdjustmentDialog } from "@/components/inventory/adjustment-dialog";
import { BatchDialog } from "@/components/inventory/batch-dialog";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { FormError, FormNotice } from "@/components/ui/field";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import {
  MOVEMENT_LABELS,
  STOCK_BADGE_VARIANTS,
  STOCK_LABELS,
  formatDate,
  formatDateTime,
  formatMoney,
  formatQuantity,
} from "@/lib/catalog";
import type {
  Category,
  InventoryDetail,
  InventoryItem,
  InventoryList,
  StockStatus,
  UnitOfMeasure,
} from "@/lib/types";

const PAGE_SIZE = 20;

const SKELETON_ROWS = ["r1", "r2", "r3", "r4", "r5"];
const SKELETON_CELLS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7"];

const primaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-xl bg-brand-700 px-3.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-800 active:translate-y-px";
const secondaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-xl border border-line bg-white px-3 py-2 text-xs font-medium text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px";

const STOCK_FILTERS: { id: "" | StockStatus; label: string }[] = [
  { id: "", label: "كل الأرصدة" },
  { id: "out", label: "نفد" },
  { id: "low", label: "قارب النفاد" },
  { id: "ok", label: "متوفر" },
];

type Reference = { units: UnitOfMeasure[]; categories: Category[] };

async function fetchReference(): Promise<Reference> {
  const [units, categories] = await Promise.all([
    apiRequest<UnitOfMeasure[]>("/api/v1/units"),
    apiRequest<Category[]>("/api/v1/categories"),
  ]);
  return { units, categories };
}

export default function InventoryPage() {
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const can = (permission: string) => permissions.includes(permission);

  const [reference, setReference] = useState<Reference>({ units: [], categories: [] });
  const { units, categories } = reference;

  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [stock, setStock] = useState<"" | StockStatus>("");
  const [categoryId, setCategoryId] = useState("");
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);

  const [result, setResult] = useState<{
    key: string;
    tenantId: string;
    data: InventoryList;
  } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InventoryDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [adjustOpen, setAdjustOpen] = useState(false);
  const [adjustProductId, setAdjustProductId] = useState<string | null>(null);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchProduct, setBatchProduct] = useState<{ id: string; name: string } | null>(null);

  const refresh = () => setRefreshKey((current) => current + 1);

  const tenantId = session?.tenant?.id ?? "";
  const params = useMemo(() => {
    const next = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (search.trim()) next.set("q", search.trim());
    if (stock) next.set("stock", stock);
    if (categoryId) next.set("category_id", categoryId);
    return next.toString();
  }, [page, search, stock, categoryId]);

  const requestKey = `${tenantId}|${params}|${refreshKey}`;
  const loading = result?.key !== requestKey && failure?.key !== requestKey;
  const data = result && result.tenantId === tenantId ? result.data : null;

  useEffect(() => {
    let cancelled = false;
    void fetchReference()
      .then((next) => {
        if (!cancelled) setReference(next);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  useEffect(() => {
    let cancelled = false;

    void apiRequest<InventoryList>(`/api/v1/inventory?${params}`)
      .then((rows) => {
        if (cancelled) return;
        setResult({ key: requestKey, tenantId, data: rows });
        setFailure(null);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setFailure({
          key: requestKey,
          message: caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل المخزون.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [params, requestKey, tenantId]);

  const loadDetail = async (productId: string) => {
    setDetailLoading(true);
    try {
      setDetail(await apiRequest<InventoryDetail>(`/api/v1/inventory/${productId}`));
    } catch (caught) {
      setDetail(null);
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل تفاصيل المخزون.");
    } finally {
      setDetailLoading(false);
    }
  };

  const toggleDetail = (item: InventoryItem) => {
    if (expandedId === item.product_id) {
      setExpandedId(null);
      setDetail(null);
      return;
    }
    setExpandedId(item.product_id);
    setDetail(null);
    void loadDetail(item.product_id);
  };

  const openAdjust = (productId: string | null) => {
    setAdjustProductId(productId);
    setAdjustOpen(true);
  };

  const items = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const failed = failure && failure.key === requestKey ? failure.message : null;
  const filtered = Boolean(search || stock || categoryId);
  const detailItem = detail?.product ?? items.find((row) => row.product_id === expandedId) ?? null;

  const clearFilters = () => {
    setQuery("");
    setSearch("");
    setStock("");
    setCategoryId("");
    setPage(1);
  };

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-5 py-8 sm:px-8">
      <FormError>{error}</FormError>
      <FormNotice>{notice}</FormNotice>

      {failed ? (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-3 p-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-ink">تعذّر تحميل المخزون</p>
              <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{failed}</p>
            </div>
            <button type="button" onClick={refresh} className={secondaryButtonClass}>
              <RefreshCw className="size-3.5" aria-hidden="true" />
              إعادة المحاولة
            </button>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardContent className="space-y-4 p-5">
          <div className="flex flex-wrap items-center gap-2">
            <form
              className="flex min-w-0 flex-1 items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                setPage(1);
                setSearch(query);
              }}
            >
              <div className="relative min-w-0 flex-1">
                <Search
                  className="pointer-events-none absolute inset-y-0 start-3 my-auto size-4 text-ink-muted"
                  aria-hidden="true"
                />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="ابحث بالاسم أو الرمز أو الباركود"
                  aria-label="بحث المخزون"
                  className="w-full rounded-xl border border-line bg-white py-2.5 pe-3 ps-9 text-sm text-ink shadow-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-200"
                />
              </div>
              <button
                type="submit"
                className="rounded-xl border border-line bg-white px-3 py-2.5 text-xs font-medium text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px"
              >
                بحث
              </button>
            </form>

            {can("inventory.adjust") ? (
              <button
                type="button"
                onClick={() => openAdjust(null)}
                className="inline-flex items-center gap-1.5 rounded-xl bg-brand-700 px-3.5 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-brand-800 active:translate-y-px"
              >
                <Plus className="size-4" aria-hidden="true" />
                تسوية مخزون
              </button>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-xs text-ink-muted">
              <SlidersHorizontal className="size-3.5" aria-hidden="true" />
              فلترة
            </span>
            <select
              value={stock}
              onChange={(event) => {
                setPage(1);
                setStock(event.target.value as "" | StockStatus);
              }}
              aria-label="فلترة بحالة الرصيد"
              className="rounded-xl border border-line bg-white px-3 py-2 text-xs text-ink outline-none focus:border-brand-500"
            >
              {STOCK_FILTERS.map((option) => (
                <option key={option.id || "all"} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              value={categoryId}
              onChange={(event) => {
                setPage(1);
                setCategoryId(event.target.value);
              }}
              aria-label="فلترة بالتصنيف"
              className="max-w-56 rounded-xl border border-line bg-white px-3 py-2 text-xs text-ink outline-none focus:border-brand-500"
            >
              <option value="">كل التصنيفات</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name_ar ?? category.name}
                </option>
              ))}
            </select>
            <span className="ms-auto text-xs text-ink-muted">
              {data ? `${formatQuantity(String(data.total))} منتج` : "\u00a0"}
            </span>
          </div>
        </CardContent>
      </Card>

      <Card className="overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[880px] text-start text-[13px]">
            <thead className="bg-surface/70 text-xs text-ink-muted">
              <tr>
                <th className="px-4 py-3 font-medium">المنتج</th>
                <th className="px-4 py-3 font-medium">التصنيف</th>
                <th className="px-4 py-3 font-medium">الرصيد</th>
                <th className="px-4 py-3 font-medium">حد التنبيه</th>
                <th className="px-4 py-3 font-medium">سعر البيع</th>
                <th className="px-4 py-3 font-medium">آخر حركة</th>
                <th className="px-4 py-3 font-medium">إجراءات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {loading && items.length === 0 ? (
                SKELETON_ROWS.map((row) => (
                  <tr key={row} className="animate-pulse">
                    {SKELETON_CELLS.map((cell) => (
                      <td key={cell} className="px-4 py-3.5">
                        <div className="h-3 rounded-full bg-line" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : items.length === 0 && !failed ? (
                <tr>
                  <td colSpan={7} className="px-4 py-14">
                    <div className="mx-auto flex max-w-sm flex-col items-center gap-3 text-center">
                      <span className="grid size-11 place-items-center rounded-2xl bg-surface text-ink-muted ring-1 ring-inset ring-line">
                        <PackageSearch className="size-5" aria-hidden="true" />
                      </span>
                      <div className="space-y-1">
                        <p className="text-sm font-medium text-ink">
                          {filtered ? "لا نتائج مطابقة" : "لا يوجد مخزون بعد"}
                        </p>
                        <p className="text-xs leading-relaxed text-ink-muted">
                          {filtered
                            ? "جرّب كلمة بحث أخرى أو امسح الفلاتر لعرض كل الأرصدة."
                            : "سجّل رصيداً افتتاحياً لمنتج ليظهر رصيده هنا."}
                        </p>
                      </div>
                      {filtered ? (
                        <button type="button" onClick={clearFilters} className={secondaryButtonClass}>
                          مسح الفلاتر
                        </button>
                      ) : (
                        <Link href="/products" className={primaryButtonClass}>
                          <Plus className="size-4" aria-hidden="true" />
                          إضافة منتج
                        </Link>
                      )}
                    </div>
                  </td>
                </tr>
              ) : (
                items.map((item) => {
                  const expanded = expandedId === item.product_id;
                  return (
                    <tr
                      key={item.product_id}
                      className={expanded ? "bg-surface/50" : "hover:bg-surface/50"}
                    >
                      <td className="px-4 py-3">
                        <p className="font-medium text-ink">{item.name_ar}</p>
                        <p className="mt-0.5 font-mono text-xs text-ink-muted" dir="ltr">
                          {item.sku}
                        </p>
                        {item.product_status === "archived" ? (
                          <Badge className="mt-1">مؤرشف</Badge>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-ink-muted">
                        {item.category_name ?? "بدون تصنيف"}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-ink">
                            {formatQuantity(item.quantity)}{" "}
                            <span className="text-xs font-normal text-ink-muted">
                              {item.base_unit_name_ar}
                            </span>
                          </span>
                          <Badge variant={STOCK_BADGE_VARIANTS[item.stock_status]}>
                            {STOCK_LABELS[item.stock_status]}
                          </Badge>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-ink-muted">
                        {formatQuantity(item.minimum_stock)}
                      </td>
                      <td className="px-4 py-3 text-ink">{formatMoney(item.sale_price)}</td>
                      <td className="px-4 py-3 text-ink-muted">{formatDateTime(item.updated_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          <button
                            type="button"
                            onClick={() => toggleDetail(item)}
                            aria-expanded={expanded}
                            className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1.5 text-xs text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px"
                          >
                            {expanded ? (
                              <ChevronUp className="size-3" aria-hidden="true" />
                            ) : (
                              <ChevronDown className="size-3" aria-hidden="true" />
                            )}
                            تفاصيل
                          </button>
                          {can("inventory.adjust") && item.product_status === "active" ? (
                            <button
                              type="button"
                              onClick={() => openAdjust(item.product_id)}
                              className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1.5 text-xs text-brand-700 transition-colors hover:border-brand-300 active:translate-y-px"
                            >
                              <Plus className="size-3" aria-hidden="true" />
                              حركة
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-ink-muted">
          <span>
            صفحة {formatQuantity(String(data?.page ?? page))} من {formatQuantity(String(totalPages))}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1 || loading}
              className="rounded-lg border border-line px-3 py-1.5 transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
            >
              السابق
            </button>
            <button
              type="button"
              onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
              disabled={page >= totalPages || loading}
              className="rounded-lg border border-line px-3 py-1.5 transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-40"
            >
              التالي
            </button>
          </div>
        </div>
      </Card>

      {expandedId ? (
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-ink">
                  {detailItem?.name_ar ?? "تفاصيل المنتج"}
                </h2>
                <p className="mt-0.5 text-xs text-ink-muted">
                  الدفعات والحركات المسجلة. السجل غير قابل للتعديل أو الحذف.
                </p>
              </div>
              {can("batches.manage") && detailItem?.tracks_batches ? (
                <button
                  type="button"
                  onClick={() => {
                    setBatchProduct({
                      id: detailItem.product_id,
                      name: detailItem.name_ar,
                    });
                    setBatchOpen(true);
                  }}
                  className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-white px-3 py-2 text-xs text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px"
                >
                  <Layers className="size-3.5" aria-hidden="true" />
                  دفعة جديدة
                </button>
              ) : null}
              <button
                type="button"
                onClick={() => {
                  setExpandedId(null);
                  setDetail(null);
                }}
                className="rounded-xl border border-line px-3 py-2 text-xs text-ink-muted transition-colors hover:border-brand-300 hover:text-ink active:translate-y-px"
              >
                إغلاق
              </button>
            </div>

            {detailLoading ? (
              <p className="flex items-center gap-2 text-xs text-ink-muted">
                <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                جارٍ تحميل التفاصيل…
              </p>
            ) : detail ? (
              <div className="grid gap-4 lg:grid-cols-2">
                <section className="space-y-2">
                  <h3 className="text-xs font-semibold text-ink">الدفعات</h3>
                  {detail.batches.length === 0 ? (
                    <p className="text-xs leading-relaxed text-ink-muted">
                      {detail.product.tracks_batches
                        ? "لا توجد دفعات بعد. أضف دفعة ثم سجّل لها حركة."
                        : "هذا المنتج لا يتتبع الدفعات."}
                    </p>
                  ) : (
                    <ul className="space-y-1.5">
                      {detail.batches.map((batch) => (
                        <li
                          key={batch.id}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-white px-3 py-2 text-xs"
                        >
                          <span className="font-mono text-ink" dir="ltr">
                            {batch.batch_number}
                          </span>
                          <span className="text-ink-muted">
                            {formatQuantity(batch.quantity)} {detail.product.base_unit_name_ar}
                          </span>
                          <span className="text-ink-muted">
                            {batch.expiry_date
                              ? `تنتهي ${formatDate(batch.expiry_date)}`
                              : "بلا تاريخ صلاحية"}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section className="space-y-2">
                  <h3 className="text-xs font-semibold text-ink">أحدث الحركات</h3>
                  {detail.movements.length === 0 ? (
                    <p className="text-xs text-ink-muted">لا توجد حركات مسجلة لهذا المنتج.</p>
                  ) : (
                    <ul className="space-y-1.5">
                      {detail.movements.map((movement) => (
                        <li
                          key={movement.id}
                          className="rounded-lg border border-line bg-white px-3 py-2 text-xs"
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-medium text-ink">
                              {MOVEMENT_LABELS[movement.movement_type]}
                            </span>
                            <span
                              className={
                                movement.direction === "in" ? "text-brand-700" : "text-red-700"
                              }
                              dir="ltr"
                            >
                              {movement.direction === "in" ? "+" : "−"}
                              {formatQuantity(movement.base_quantity.replace("-", ""))}{" "}
                              {detail.product.base_unit_name_ar}
                            </span>
                          </div>
                          <p className="mt-1 text-ink-muted">
                            {formatDateTime(movement.created_at)}
                            {movement.created_by_name ? ` · ${movement.created_by_name}` : ""}
                          </p>
                          {movement.notes ? (
                            <p className="mt-1 leading-relaxed text-ink-muted">{movement.notes}</p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-3">
                <p className="text-xs text-ink-muted">تعذّر عرض التفاصيل.</p>
                <button
                  type="button"
                  onClick={() => {
                    if (expandedId) void loadDetail(expandedId);
                  }}
                  className={secondaryButtonClass}
                >
                  <RefreshCw className="size-3.5" aria-hidden="true" />
                  إعادة المحاولة
                </button>
              </div>
            )}
          </CardContent>
        </Card>
      ) : null}

      {adjustOpen ? (
        <AdjustmentDialog
          products={items}
          initialProductId={adjustProductId}
          canSetCost={can("inventory.view_cost")}
          units={units}
          onClose={() => setAdjustOpen(false)}
          onSaved={(message) => {
            setNotice(message);
            refresh();
            if (expandedId) void loadDetail(expandedId);
          }}
        />
      ) : null}

      {batchOpen ? (
        <BatchDialog
          productId={batchProduct?.id ?? null}
          productName={batchProduct?.name ?? null}
          onClose={() => setBatchOpen(false)}
          onCreated={(message) => {
            setNotice(message);
            refresh();
            if (expandedId) void loadDetail(expandedId);
          }}
        />
      ) : null}
    </div>
  );
}
