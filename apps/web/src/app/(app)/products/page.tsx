"use client";

import { Archive, Loader2, PackageSearch, Pencil, Plus, RotateCcw, Tags } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ProductDialog } from "@/components/catalog/product-dialog";
import { TaxonomyDialog } from "@/components/catalog/taxonomy-dialog";
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
import { ApiRequestError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatMoney, toNumber } from "@/lib/catalog";
import type { Brand, Category, Product, ProductDetail, ProductList, UnitOfMeasure } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

type StatusFilter = "" | "active" | "archived";

const STATUS_FILTERS: { id: StatusFilter; label: string }[] = [
  { id: "active", label: "النشطة" },
  { id: "archived", label: "المؤرشفة" },
  { id: "", label: "الكل" },
];

type Reference = { units: UnitOfMeasure[]; categories: Category[]; brands: Brand[] };

async function fetchReference(): Promise<Reference> {
  const [units, categories, brands] = await Promise.all([
    apiRequest<UnitOfMeasure[]>("/api/v1/units"),
    apiRequest<Category[]>("/api/v1/categories"),
    apiRequest<Brand[]>("/api/v1/brands"),
  ]);
  return { units, categories, brands };
}

/** Gross margin on the sale price, the figure owners usually keep in a spreadsheet column. */
function margin(product: Product): string {
  const sale = toNumber(product.sale_price);
  const cost = toNumber(product.cost_price);
  if (!product.sale_price || !product.cost_price || sale <= 0) return "—";
  return `${Math.round(((sale - cost) / sale) * 100)}%`;
}

export default function ProductsPage() {
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const can = (permission: string) => permissions.includes(permission);
  const showCost = can("inventory.view_cost");

  const [reference, setReference] = useState<Reference>({ units: [], categories: [], brands: [] });
  const { units, categories, brands } = reference;

  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<StatusFilter>("active");
  const [categoryId, setCategoryId] = useState("");
  const [page, setPage] = useState(1);

  const [result, setResult] = useState<{ key: string; tenantId: string; data: ProductList } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(() => initialParam("new") === "1" && can("products.create"));
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
          message: caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل المنتجات.",
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
      // The list still works without reference data; the form explains what is missing.
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
      setEditing(await apiRequest<ProductDetail>(`/api/v1/products/${product.id}`));
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
        setNotice(`أُرشف «${product.name_ar}». تجده في تبويب «المؤرشفة» ويمكن استعادته في أي وقت.`);
      } else {
        await apiRequest<ProductDetail>(`/api/v1/products/${product.id}/restore`, { method: "POST" });
        setNotice(`استُعيد «${product.name_ar}» إلى المنتجات النشطة.`);
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
  const filtered = Boolean(search || categoryId || status === "archived");

  const clearFilters = () => {
    setQuery("");
    setSearch("");
    setStatus("active");
    setCategoryId("");
    setPage(1);
  };

  const rowActions = (product: Product) => {
    const busy = busyId === product.id;
    return (
      <div className="flex items-center justify-end gap-1">
        {can("products.update") && product.status === "active" ? (
          <button
            type="button"
            onClick={() => void openEdit(product)}
            disabled={busy}
            className={buttonClass("ghost", "sm")}
            aria-label={`تعديل ${product.name_ar}`}
          >
            {busy ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <Pencil className="size-3.5" aria-hidden="true" />
            )}
            تعديل
          </button>
        ) : null}
        {can("products.archive") ? (
          <button
            type="button"
            onClick={() => void changeStatus(product, product.status === "active" ? "archive" : "restore")}
            disabled={busy}
            className={buttonClass(product.status === "active" ? "ghost" : "secondary", "sm")}
            aria-label={`${product.status === "active" ? "أرشفة" : "استعادة"} ${product.name_ar}`}
          >
            {product.status === "active" ? (
              <Archive className="size-3.5" aria-hidden="true" />
            ) : (
              <RotateCcw className="size-3.5" aria-hidden="true" />
            )}
            {product.status === "active" ? "أرشفة" : "استعادة"}
          </button>
        ) : null}
      </div>
    );
  };

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
          label="بحث في المنتجات"
          placeholder="اسم المنتج أو رمزه أو الباركود"
        />
        <Segmented
          label="حالة المنتج"
          value={status}
          options={STATUS_FILTERS}
          onChange={(value) => {
            setPage(1);
            setStatus(value);
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
        <div className="ms-auto flex gap-2">
          {can("categories.manage") ? (
            <button type="button" onClick={() => setTaxonomyOpen(true)} className={buttonClass("secondary", "md")}>
              <Tags className="size-4" aria-hidden="true" />
              التصنيفات
            </button>
          ) : null}
          {can("products.create") ? (
            <button type="button" onClick={openCreate} className={buttonClass("primary", "md")}>
              <Plus className="size-4" aria-hidden="true" />
              منتج جديد
            </button>
          ) : null}
        </div>
      </div>

      {failed ? <LoadError message={failed} onRetry={refresh} /> : null}

      <Card className="overflow-hidden">
        {loading && items.length === 0 ? (
          <SkeletonRows />
        ) : items.length === 0 && !failed ? (
          <EmptyState
            icon={PackageSearch}
            title={filtered ? "لا توجد نتائج" : "لا توجد منتجات بعد"}
            body={
              filtered
                ? "لا يوجد منتج يطابق البحث أو الفلتر الحالي."
                : "أضف أول منتج: الاسم، الرمز، الوحدة، السعر، والحد الأدنى للتنبيه."
            }
            action={
              filtered ? (
                <button type="button" onClick={clearFilters} className={buttonClass("secondary", "sm")}>
                  مسح الفلاتر
                </button>
              ) : can("products.create") ? (
                <button type="button" onClick={openCreate} className={buttonClass("primary", "sm")}>
                  <Plus className="size-4" aria-hidden="true" />
                  إضافة منتج
                </button>
              ) : null
            }
          />
        ) : (
          <div className={cn(loading && "opacity-60 transition-opacity")}>
            <table className="hidden w-full md:table">
              <thead className="border-b border-line bg-surface/60">
                <tr>
                  <Th>المنتج</Th>
                  <Th>التصنيف</Th>
                  <Th className="w-44">الرصيد</Th>
                  <Th className="text-end">سعر البيع</Th>
                  {showCost ? <Th className="text-end">التكلفة</Th> : null}
                  {showCost ? <Th className="text-end">الهامش</Th> : null}
                  <Th>
                    <span className="sr-only">إجراءات</span>
                  </Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((product) => (
                  <tr key={product.id} className="transition-colors hover:bg-brand-50/40">
                    <Td>
                      <p className="font-medium text-ink">{product.name_ar}</p>
                      <p className="text-xs text-ink-muted" dir="ltr">
                        {product.sku}
                        {product.barcode ? `  ·  ${product.barcode}` : ""}
                      </p>
                      {product.status === "archived" ? <Badge className="mt-1">مؤرشف</Badge> : null}
                    </Td>
                    <Td className="text-sm text-ink-muted">{product.category_name ?? "—"}</Td>
                    <Td>
                      <StockGauge
                        quantity={product.stock_quantity}
                        minimum={product.minimum_stock}
                        status={product.stock_status}
                        unit={product.base_unit_name_ar}
                      />
                    </Td>
                    <Td className="tabular text-end text-sm font-medium text-ink">{formatMoney(product.sale_price)}</Td>
                    {showCost ? (
                      <Td className="tabular text-end text-sm text-ink-muted">{formatMoney(product.cost_price)}</Td>
                    ) : null}
                    {showCost ? <Td className="tabular text-end text-sm text-ink-muted">{margin(product)}</Td> : null}
                    <Td>{rowActions(product)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>

            <ul className="divide-y divide-line md:hidden">
              {items.map((product) => (
                <li key={product.id} className="space-y-3 px-4 py-4">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-ink">{product.name_ar}</p>
                      <p className="text-xs text-ink-muted">
                        <span dir="ltr">{product.sku}</span>
                        {product.category_name ? `، ${product.category_name}` : ""}
                      </p>
                      {product.status === "archived" ? <Badge className="mt-1">مؤرشف</Badge> : null}
                    </div>
                    <div className="text-end">
                      <p className="tabular text-sm font-medium text-ink">{formatMoney(product.sale_price)}</p>
                      {showCost ? (
                        <p className="tabular text-xs text-ink-muted">هامش {margin(product)}</p>
                      ) : null}
                    </div>
                  </div>
                  <StockGauge
                    quantity={product.stock_quantity}
                    minimum={product.minimum_stock}
                    status={product.stock_status}
                    unit={product.base_unit_name_ar}
                  />
                  {rowActions(product)}
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

      {/* The form picks its default unit on mount, so wait for the unit list. */}
      {dialogOpen && (editing || units.length > 0) ? (
        <ProductDialog
          product={editing}
          units={units}
          categories={categories}
          brands={brands}
          canSetCost={showCost}
          onClose={() => {
            setDialogOpen(false);
            if (window.location.search.includes("new=1")) window.history.replaceState(null, "", "/products");
          }}
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
