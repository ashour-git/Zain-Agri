"use client";

import {
  Archive,
  Loader2,
  PackageSearch,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Tags,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ProductDialog } from "@/components/catalog/product-dialog";
import { TaxonomyDialog } from "@/components/catalog/taxonomy-dialog";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { FormError, FormNotice } from "@/components/ui/field";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { STOCK_BADGE_VARIANTS, STOCK_LABELS, formatMoney, formatQuantity } from "@/lib/catalog";
import type {
  Brand,
  Category,
  Product,
  ProductDetail,
  ProductList,
  UnitOfMeasure,
} from "@/lib/types";

const PAGE_SIZE = 20;

const SKELETON_ROWS = ["r1", "r2", "r3", "r4", "r5"];
const SKELETON_CELLS = ["c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];

const primaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-xl bg-brand-700 px-3.5 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-800 active:translate-y-px";
const secondaryButtonClass =
  "inline-flex items-center gap-1.5 rounded-xl border border-line bg-white px-3 py-2 text-xs font-medium text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px";

type Reference = {
  units: UnitOfMeasure[];
  categories: Category[];
  brands: Brand[];
};

async function fetchReference(): Promise<Reference> {
  const [units, categories, brands] = await Promise.all([
    apiRequest<UnitOfMeasure[]>("/api/v1/units"),
    apiRequest<Category[]>("/api/v1/categories"),
    apiRequest<Brand[]>("/api/v1/brands"),
  ]);
  return { units, categories, brands };
}

export default function ProductsPage() {
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const can = (permission: string) => permissions.includes(permission);

  const [reference, setReference] = useState<Reference>({
    units: [],
    categories: [],
    brands: [],
  });
  const { units, categories, brands } = reference;

  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"" | "active" | "archived">("");
  const [categoryId, setCategoryId] = useState("");
  const [page, setPage] = useState(1);

  const [result, setResult] = useState<{
    key: string;
    tenantId: string;
    data: ProductList;
  } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProductDetail | null>(null);
  const [taxonomyOpen, setTaxonomyOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = () => setRefreshKey((current) => current + 1);

  const tenantId = session?.tenant?.id ?? "";
  const params = useMemo(() => {
    const next = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (search.trim()) next.set("q", search.trim());
    if (status) next.set("status", status);
    if (categoryId) next.set("category_id", categoryId);
    return next.toString();
  }, [page, search, status, categoryId]);

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

    void apiRequest<ProductList>(`/api/v1/products?${params}`)
      .then((rows) => {
        if (cancelled) return;
        setResult({ key: requestKey, tenantId, data: rows });
        setFailure(null);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setFailure({
          key: requestKey,
          message:
            caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل المنتجات.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [params, requestKey, tenantId]);

  const loadReference = async () => {
    try {
      setReference(await fetchReference());
    } catch {
      // The list still works without reference data; the form will explain.
    }
  };

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = async (product: Product) => {
    setBusyId(product.id);
    setError(null);
    try {
      const detail = await apiRequest<ProductDetail>(`/api/v1/products/${product.id}`);
      setEditing(detail);
      setDialogOpen(true);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل المنتج.");
    } finally {
      setBusyId(null);
    }
  };

  const changeStatus = async (product: Product, action: "archive" | "restore") => {
    setBusyId(product.id);
    setError(null);
    try {
      if (action === "archive") {
        await apiRequest<ProductDetail>(`/api/v1/products/${product.id}`, { method: "DELETE" });
        setNotice(`تم أرشفة ${product.name_ar}.`);
      } else {
        await apiRequest<ProductDetail>(`/api/v1/products/${product.id}/restore`, {
          method: "POST",
        });
        setNotice(`تم استعادة ${product.name_ar}.`);
      }
      refresh();
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر تحديث حالة المنتج.");
    } finally {
      setBusyId(null);
    }
  };

  const items = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;
  const failed = failure && failure.key === requestKey ? failure.message : null;
  const filtered = Boolean(search || status || categoryId);
  const columnCount = can("inventory.view_cost") ? 8 : 7;

  const clearFilters = () => {
    setQuery("");
    setSearch("");
    setStatus("");
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
              <p className="text-sm font-medium text-ink">تعذّر تحميل المنتجات</p>
              <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{failed}</p>
            </div>
            <button
              type="button"
              onClick={refresh}
              className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-white px-3 py-2 text-xs font-medium text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px"
            >
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
                  aria-label="بحث المنتجات"
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

            {can("categories.manage") ? (
              <button
                type="button"
                onClick={() => setTaxonomyOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-xl border border-line bg-white px-3 py-2.5 text-xs text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px"
              >
                <Tags className="size-4" aria-hidden="true" />
                التصنيفات
              </button>
            ) : null}

            {can("products.create") ? (
              <button
                type="button"
                onClick={openCreate}
                className="inline-flex items-center gap-1.5 rounded-xl bg-brand-700 px-3.5 py-2.5 text-xs font-semibold text-white transition-colors hover:bg-brand-800 active:translate-y-px"
              >
                <Plus className="size-4" aria-hidden="true" />
                منتج جديد
              </button>
            ) : null}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              value={status}
              onChange={(event) => {
                setPage(1);
                setStatus(event.target.value as "" | "active" | "archived");
              }}
              aria-label="فلترة بالحالة"
              className="rounded-xl border border-line bg-white px-3 py-2 text-xs text-ink outline-none focus:border-brand-500"
            >
              <option value="">كل الحالات</option>
              <option value="active">نشط</option>
              <option value="archived">مؤرشف</option>
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
          <table className="w-full min-w-[860px] text-start text-[13px]">
            <thead className="bg-surface/70 text-xs text-ink-muted">
              <tr>
                <th className="px-4 py-3 font-medium">المنتج</th>
                <th className="px-4 py-3 font-medium">التصنيف</th>
                <th className="px-4 py-3 font-medium">الوحدة</th>
                <th className="px-4 py-3 font-medium">الرصيد</th>
                <th className="px-4 py-3 font-medium">سعر البيع</th>
                {can("inventory.view_cost") ? (
                  <th className="px-4 py-3 font-medium">التكلفة</th>
                ) : null}
                <th className="px-4 py-3 font-medium">الحالة</th>
                <th className="px-4 py-3 font-medium">إجراءات</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {loading && items.length === 0 ? (
                SKELETON_ROWS.map((row) => (
                  <tr key={row} className="animate-pulse">
                    {SKELETON_CELLS.slice(0, columnCount).map((cell) => (
                      <td key={cell} className="px-4 py-3.5">
                        <div className="h-3 rounded-full bg-line" />
                      </td>
                    ))}
                  </tr>
                ))
              ) : items.length === 0 && !failed ? (
                <tr>
                  <td colSpan={columnCount} className="px-4 py-14">
                    <div className="mx-auto flex max-w-sm flex-col items-center gap-3 text-center">
                      <span className="grid size-11 place-items-center rounded-2xl bg-surface text-ink-muted ring-1 ring-inset ring-line">
                        <PackageSearch className="size-5" aria-hidden="true" />
                      </span>
                      <div className="space-y-1">
                        <p className="text-sm font-medium text-ink">
                          {filtered ? "لا نتائج مطابقة" : "لا توجد منتجات بعد"}
                        </p>
                        <p className="text-xs leading-relaxed text-ink-muted">
                          {filtered
                            ? "جرّب كلمة بحث أخرى أو امسح الفلاتر لعرض كل المنتجات."
                            : "أضف أول منتج ليظهر هنا مع رصيده وأسعاره."}
                        </p>
                      </div>
                      {filtered ? (
                        <button type="button" onClick={clearFilters} className={secondaryButtonClass}>
                          مسح الفلاتر
                        </button>
                      ) : can("products.create") ? (
                        <button type="button" onClick={openCreate} className={primaryButtonClass}>
                          <Plus className="size-4" aria-hidden="true" />
                          إضافة منتج
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ) : (
                items.map((product) => (
                  <tr key={product.id} className="hover:bg-surface/50">
                    <td className="px-4 py-3">
                      <p className="font-medium text-ink">{product.name_ar}</p>
                      <p className="mt-0.5 font-mono text-xs text-ink-muted" dir="ltr">
                        {product.sku}
                        {product.barcode ? ` · ${product.barcode}` : ""}
                      </p>
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {product.category_name ?? "بدون تصنيف"}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{product.base_unit_name_ar}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-ink">
                          {formatQuantity(product.stock_quantity)}
                        </span>
                        <Badge variant={STOCK_BADGE_VARIANTS[product.stock_status]}>
                          {STOCK_LABELS[product.stock_status]}
                        </Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-ink">{formatMoney(product.sale_price)}</td>
                    {can("inventory.view_cost") ? (
                      <td className="px-4 py-3 text-ink-muted">
                        {formatMoney(product.cost_price)}
                      </td>
                    ) : null}
                    <td className="px-4 py-3">
                      <Badge variant={product.status === "active" ? "lime" : "neutral"}>
                        {product.status === "active" ? "نشط" : "مؤرشف"}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1.5">
                        {can("products.update") && product.status === "active" ? (
                          <button
                            type="button"
                            onClick={() => void openEdit(product)}
                            disabled={busyId === product.id}
                            className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1.5 text-xs text-ink-muted transition-colors hover:border-brand-300 hover:text-brand-700 active:translate-y-px disabled:opacity-50"
                          >
                            {busyId === product.id ? (
                              <Loader2 className="size-3 animate-spin" aria-hidden="true" />
                            ) : (
                              <Pencil className="size-3" aria-hidden="true" />
                            )}
                            تعديل
                          </button>
                        ) : null}

                        {can("products.archive") ? (
                          <button
                            type="button"
                            onClick={() =>
                              void changeStatus(
                                product,
                                product.status === "active" ? "archive" : "restore",
                              )
                            }
                            disabled={busyId === product.id}
                            className="inline-flex items-center gap-1 rounded-lg border border-line px-2 py-1.5 text-xs text-ink-muted transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-700 active:translate-y-px disabled:opacity-50"
                          >
                            {product.status === "active" ? (
                              <Archive className="size-3" aria-hidden="true" />
                            ) : (
                              <RotateCcw className="size-3" aria-hidden="true" />
                            )}
                            {product.status === "active" ? "أرشفة" : "استعادة"}
                          </button>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))
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

      {dialogOpen ? (
        <ProductDialog
          product={editing}
          units={units}
          categories={categories}
          brands={brands}
          canSetCost={can("inventory.view_cost")}
          onClose={() => setDialogOpen(false)}
          onSaved={(message) => {
            setNotice(message);
            refresh();
          }}
        />
      ) : null}

      {taxonomyOpen ? (
        <TaxonomyDialog
          categories={categories}
          onClose={() => setTaxonomyOpen(false)}
          onCreated={(message) => {
            setNotice(message);
            void loadReference();
          }}
        />
      ) : null}
    </div>
  );
}
