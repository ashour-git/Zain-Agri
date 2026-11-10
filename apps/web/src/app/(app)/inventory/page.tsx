"use client";

import { Layers, Loader2, PackageSearch, Plus, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

import { StockGauge } from "@/components/inventory/stock-gauge";
import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  EmptyState,
  LoadError,
  Pagination,
  SearchBox,
  Segmented,
  SkeletonRows,
  Td,
  Th,
  initialParam,
  selectClass,
} from "@/components/ui/data";
import { FormError, FormNotice } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { getCategories, getUnits } from "@/lib/reference";
import { MOVEMENT_LABELS, formatDate, formatDateTime, formatMoney, formatQuantity } from "@/lib/catalog";
import type {
  Category,
  InventoryDetail,
  InventoryItem,
  InventoryList,
  StockStatus,
  UnitOfMeasure,
} from "@/lib/types";
import { cn } from "@/lib/utils";

// Dialogs download on first open; most visits never open them.
const AdjustmentDialog = dynamic(() => import("@/components/inventory/adjustment-dialog").then((module) => module.AdjustmentDialog), {
  ssr: false,
});
const BatchDialog = dynamic(() => import("@/components/inventory/batch-dialog").then((module) => module.BatchDialog), {
  ssr: false,
});

const PAGE_SIZE = 25;

const STOCK_FILTERS: { id: "" | StockStatus; label: string }[] = [
  { id: "", label: "الكل" },
  { id: "low", label: "تحت الحد" },
  { id: "out", label: "نفد" },
  { id: "ok", label: "متوفر" },
];

type Reference = { units: UnitOfMeasure[]; categories: Category[] };

async function fetchReference(tenantId: string): Promise<Reference> {
  const [units, categories] = await Promise.all([getUnits(), getCategories(tenantId)]);
  return { units, categories };
}

function initialStock(): "" | StockStatus {
  const value = initialParam("stock");
  return value === "low" || value === "out" || value === "ok" ? value : "";
}

export default function InventoryPage() {
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const can = (permission: string) => permissions.includes(permission);

  const [reference, setReference] = useState<Reference>({ units: [], categories: [] });
  const { units, categories } = reference;

  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [stock, setStock] = useState<"" | StockStatus>(initialStock);
  const [categoryId, setCategoryId] = useState("");
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);

  const [result, setResult] = useState<{ key: string; tenantId: string; data: InventoryList } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [detailId, setDetailId] = useState<string | null>(null);
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
    void fetchReference(tenantId)
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

  const openDetail = (item: InventoryItem) => {
    setDetailId(item.product_id);
    setDetail(null);
    void loadDetail(item.product_id);
  };

  const closeDetail = () => {
    setDetailId(null);
    setDetail(null);
  };

  const openAdjust = (productId: string | null) => {
    setAdjustProductId(productId);
    setAdjustOpen(true);
  };

  const items = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const failed = failure && failure.key === requestKey ? failure.message : null;
  const filtered = Boolean(search || stock || categoryId);
  const detailItem = detail?.product ?? items.find((row) => row.product_id === detailId) ?? null;
  const canAdjust = can("inventory.adjust");

  const clearFilters = () => {
    setQuery("");
    setSearch("");
    setStock("");
    setCategoryId("");
    setPage(1);
  };

  const rowActions = (item: InventoryItem) => (
    <div className="flex items-center justify-end gap-1">
      <button type="button" onClick={() => openDetail(item)} className={buttonClass("ghost", "sm")}>
        السجل
      </button>
      {canAdjust && item.product_status === "active" ? (
        <button type="button" onClick={() => openAdjust(item.product_id)} className={buttonClass("secondary", "sm")}>
          <SlidersHorizontal className="size-3.5" aria-hidden="true" />
          تسوية
        </button>
      ) : null}
    </div>
  );

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-6 sm:px-8 sm:py-8">
      <FormError>{error}</FormError>
      <FormNotice>{notice}</FormNotice>

      <div className="flex flex-wrap items-center gap-2">
        <SearchBox
          value={query}
          onChange={setQuery}
          onSubmit={() => {
            setPage(1);
            setSearch(query);
          }}
          label="بحث في المخزون"
          placeholder="اسم المنتج أو رمزه أو الباركود"
        />
        <Segmented
          label="حالة الرصيد"
          value={stock}
          options={STOCK_FILTERS}
          onChange={(value) => {
            setPage(1);
            setStock(value);
          }}
        />
        <select
          value={categoryId}
          onChange={(event) => {
            setPage(1);
            setCategoryId(event.target.value);
          }}
          aria-label="التصنيف"
          className={cn(selectClass, "max-w-48")}
        >
          <option value="">كل التصنيفات</option>
          {categories.map((category) => (
            <option key={category.id} value={category.id}>
              {category.name_ar ?? category.name}
            </option>
          ))}
        </select>
        {canAdjust ? (
          <button type="button" onClick={() => openAdjust(null)} className={buttonClass("primary", "md", "ms-auto")}>
            <Plus className="size-4" aria-hidden="true" />
            تسوية مخزون
          </button>
        ) : null}
      </div>

      {failed ? <LoadError message={failed} onRetry={refresh} /> : null}

      <Card className="overflow-hidden">
        {loading && items.length === 0 ? (
          <SkeletonRows />
        ) : items.length === 0 && !failed ? (
          <EmptyState
            icon={PackageSearch}
            title={filtered ? "لا توجد نتائج" : "لا توجد منتجات في المخزون"}
            body={
              filtered
                ? "لا يوجد منتج يطابق البحث أو الفلتر الحالي."
                : "أضف منتجاتك أولاً، ثم سجّل رصيدها الحالي من زر «تسوية مخزون»."
            }
            action={
              filtered ? (
                <button type="button" onClick={clearFilters} className={buttonClass("secondary", "sm")}>
                  مسح الفلاتر
                </button>
              ) : (
                <Link href="/products?new=1" className={buttonClass("primary", "sm")}>
                  <Plus className="size-4" aria-hidden="true" />
                  إضافة منتج
                </Link>
              )
            }
          />
        ) : (
          <div className={cn(loading && "opacity-60 transition-opacity")}>
            {/* Desktop: the sheet. */}
            <table className="hidden w-full md:table">
              <thead className="border-b border-line bg-surface/60">
                <tr>
                  <Th>المنتج</Th>
                  <Th>التصنيف</Th>
                  <Th className="w-48">الرصيد</Th>
                  <Th className="text-end">سعر البيع</Th>
                  <Th>آخر تحديث</Th>
                  <Th>
                    <span className="sr-only">إجراءات</span>
                  </Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((item) => (
                  <tr key={item.product_id} className="transition-colors hover:bg-brand-50/40">
                    <Td>
                      <p className="font-medium text-ink">{item.name_ar}</p>
                      <p className="text-xs text-ink-muted" dir="ltr">
                        {item.sku}
                      </p>
                      {item.product_status === "archived" ? <Badge className="mt-1">مؤرشف</Badge> : null}
                    </Td>
                    <Td className="text-sm text-ink-muted">{item.category_name ?? "—"}</Td>
                    <Td>
                      <StockGauge
                        quantity={item.quantity}
                        minimum={item.minimum_stock}
                        status={item.stock_status}
                        unit={item.base_unit_name_ar}
                      />
                    </Td>
                    <Td className="tabular text-end text-sm text-ink">{formatMoney(item.sale_price)}</Td>
                    <Td className="text-sm text-ink-muted">{formatDate(item.updated_at)}</Td>
                    <Td>{rowActions(item)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Phone: one row per product, actions always visible. */}
            <ul className="divide-y divide-line md:hidden">
              {items.map((item) => (
                <li key={item.product_id} className="space-y-3 px-4 py-4">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-ink">{item.name_ar}</p>
                      <p className="text-xs text-ink-muted">
                        <span dir="ltr">{item.sku}</span>
                        {item.category_name ? `، ${item.category_name}` : ""}
                      </p>
                    </div>
                    <span className="tabular text-sm text-ink">{formatMoney(item.sale_price)}</span>
                  </div>
                  <StockGauge
                    quantity={item.quantity}
                    minimum={item.minimum_stock}
                    status={item.stock_status}
                    unit={item.base_unit_name_ar}
                  />
                  {rowActions(item)}
                </li>
              ))}
            </ul>
          </div>
        )}

        {data && data.total > 0 ? (
          <Pagination
            page={data.page}
            totalPages={totalPages}
            total={data.total}
            noun="منتج"
            disabled={loading}
            onChange={setPage}
          />
        ) : null}
      </Card>

      <Modal
        open={detailId !== null}
        onClose={closeDetail}
        title={detailItem?.name_ar ?? "سجل المنتج"}
        description="الدفعات وكل حركة دخلت أو خرجت. السجل لا يُعدَّل ولا يُحذف."
        wide
      >
        {detailLoading ? (
          <p className="flex items-center gap-2 py-6 text-sm text-ink-muted">
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
            جارٍ التحميل…
          </p>
        ) : detail ? (
          <div className="space-y-6">
            <StockGauge
              className="max-w-xs"
              quantity={detail.product.quantity}
              minimum={detail.product.minimum_stock}
              status={detail.product.stock_status}
              unit={detail.product.base_unit_name_ar}
            />

            <section className="space-y-2">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-ink">الدفعات</h3>
                {can("batches.manage") && detail.product.tracks_batches ? (
                  <button
                    type="button"
                    onClick={() => {
                      setBatchProduct({ id: detail.product.product_id, name: detail.product.name_ar });
                      setBatchOpen(true);
                    }}
                    className={buttonClass("secondary", "sm")}
                  >
                    <Layers className="size-3.5" aria-hidden="true" />
                    دفعة جديدة
                  </button>
                ) : null}
              </div>
              {detail.batches.length === 0 ? (
                <p className="text-sm text-ink-muted">
                  {detail.product.tracks_batches
                    ? "لا توجد دفعات بعد. أضف دفعة ثم سجّل لها حركة."
                    : "هذا المنتج لا يتتبع الدفعات وتواريخ الصلاحية."}
                </p>
              ) : (
                <div className="overflow-x-auto rounded-md border border-line">
                  <table className="w-full text-sm">
                    <thead className="bg-surface/60">
                      <tr>
                        <Th>رقم الدفعة</Th>
                        <Th className="text-end">الكمية</Th>
                        <Th>الصلاحية</Th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {detail.batches.map((batch) => (
                        <tr key={batch.id}>
                          <Td>
                            <span dir="ltr">{batch.batch_number}</span>
                          </Td>
                          <Td className="tabular text-end">{formatQuantity(batch.quantity)}</Td>
                          <Td className="text-ink-muted">
                            {batch.expiry_date ? formatDate(batch.expiry_date) : "بدون تاريخ"}
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-ink">الحركات</h3>
              {detail.movements.length === 0 ? (
                <p className="text-sm text-ink-muted">لم تُسجَّل حركات لهذا المنتج بعد.</p>
              ) : (
                <div className="overflow-x-auto rounded-md border border-line">
                  <table className="w-full min-w-[520px] text-sm">
                    <thead className="bg-surface/60">
                      <tr>
                        <Th>النوع</Th>
                        <Th className="text-end">الكمية</Th>
                        <Th>التاريخ</Th>
                        <Th>بواسطة</Th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {detail.movements.map((movement) => (
                        <tr key={movement.id}>
                          <Td>
                            <p className="text-ink">{MOVEMENT_LABELS[movement.movement_type]}</p>
                            {movement.notes ? <p className="text-xs text-ink-muted">{movement.notes}</p> : null}
                          </Td>
                          <Td
                            className={cn(
                              "tabular text-end font-medium",
                              movement.direction === "in" ? "text-brand-700" : "text-accent-700",
                            )}
                          >
                            <span dir="ltr">
                              {movement.direction === "in" ? "+" : "−"}
                              {formatQuantity(movement.base_quantity.replace("-", ""))}
                            </span>
                          </Td>
                          <Td className="whitespace-nowrap text-ink-muted">{formatDateTime(movement.created_at)}</Td>
                          <Td className="text-ink-muted">{movement.created_by_name ?? "—"}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>

            {canAdjust && detail.product.product_status === "active" ? (
              <div className="flex justify-end border-t border-line pt-4">
                <button
                  type="button"
                  onClick={() => {
                    // One dialog at a time: the adjustment replaces the history view.
                    const productId = detail.product.product_id;
                    closeDetail();
                    openAdjust(productId);
                  }}
                  className={buttonClass("primary", "md")}
                >
                  <SlidersHorizontal className="size-4" aria-hidden="true" />
                  تسوية مخزون لهذا المنتج
                </button>
              </div>
            ) : null}
          </div>
        ) : (
          <LoadError
            message="تعذّر عرض سجل المنتج."
            onRetry={() => {
              if (detailId) void loadDetail(detailId);
            }}
          />
        )}
      </Modal>

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
            if (detailId) void loadDetail(detailId);
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
            if (detailId) void loadDetail(detailId);
          }}
        />
      ) : null}
    </div>
  );
}
