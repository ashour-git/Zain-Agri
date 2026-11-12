"use client";

import { ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, PageHeader } from "@/components/ui/card";
import { EmptyState, LoadError, SkeletonRows, selectClass } from "@/components/ui/data";
import { Field, FormError, FormNotice } from "@/components/ui/field";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatDateTime } from "@/lib/catalog";
import { getCategories } from "@/lib/reference";
import { STATUS_LABELS, type Stocktake, listStocktakes, startStocktake } from "@/lib/stocktake";
import type { Category } from "@/lib/types";

const STATUS_VARIANT = { open: "warning", applied: "brand", cancelled: "neutral" } as const;

/** Shown after an apply: /inventory/stocktake?done=<corrections>. */
function DoneNotice() {
  const done = useSearchParams().get("done");
  if (done === null) return null;
  return (
    <FormNotice>
      {Number(done) === 0 ? "اعتُمد الجرد ولم تكن هناك فروق." : `اعتُمد الجرد وسُجّل ${done} تصحيح على المخزون.`}
    </FormNotice>
  );
}

export default function StocktakeListPage() {
  const { session } = useAuth();
  const router = useRouter();
  const canCount = session?.permissions.includes("inventory.adjust") ?? false;

  const [items, setItems] = useState<Stocktake[] | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [failed, setFailed] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [blind, setBlind] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    listStocktakes()
      .then((result) => {
        setFailed(null);
        setItems(result.items);
      })
      .catch((caught: unknown) =>
        setFailed(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل الجرد."),
      );
  };

  useEffect(() => {
    if (!canCount) return;
    load();
    if (session?.tenant?.id) {
      void getCategories(session.tenant.id).then(setCategories).catch(() => setCategories([]));
    }
  }, [canCount, session?.tenant?.id]);

  if (!canCount) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <FormError>ليست لديك صلاحية الجرد. اطلبها من مالك المتجر.</FormError>
      </div>
    );
  }

  const open = items?.find((row) => row.status === "open") ?? null;

  const onStart = async () => {
    setStarting(true);
    setError(null);
    try {
      const created = await startStocktake({
        scope: categoryId ? "category" : "all",
        category_id: categoryId || undefined,
        name: name.trim() || undefined,
        blind,
      });
      router.push(`/inventory/stocktake/${created.id}`);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر بدء الجرد.");
      setStarting(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-5 py-8 sm:px-8">
      <PageHeader
        title="الجرد"
        description="عُدّ ما على الأرفف، راجع الفروق، ثم اعتمدها دفعة واحدة."
        actions={
          <Link href="/inventory" className={buttonClass("ghost", "sm")}>
            العودة إلى المخزون
          </Link>
        }
      />

      <Suspense fallback={null}>
        <DoneNotice />
      </Suspense>
      <FormError>{error}</FormError>

      {open ? (
        <Card className="border-accent-300 bg-accent-50">
          <CardHeader>
            <CardTitle>لديك جرد مفتوح</CardTitle>
            <CardDescription>
              {open.name}: عُدّ {open.counted_lines} من {open.total_lines}. أكمله أو ألغه قبل بدء جرد جديد.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href={`/inventory/stocktake/${open.id}`} className={buttonClass("primary")}>
              متابعة الجرد
            </Link>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ClipboardCheck className="size-4 text-brand-600" aria-hidden="true" />
              بدء جرد جديد
            </CardTitle>
            <CardDescription>
              اختر تصنيفًا لجرد قسم واحد، أو اتركه لجرد كل المنتجات النشطة.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Field
              label="اسم الجرد (اختياري)"
              name="stocktake-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="جرد آخر الشهر"
              maxLength={120}
            />
            <div className="space-y-1.5">
              <label htmlFor="stocktake-category" className="block text-[13px] font-medium text-ink">
                التصنيف
              </label>
              <select
                id="stocktake-category"
                value={categoryId}
                onChange={(event) => setCategoryId(event.target.value)}
                className={selectClass}
              >
                <option value="">كل المنتجات</option>
                {categories.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name_ar ?? category.name}
                  </option>
                ))}
              </select>
            </div>
            <label className="flex items-start gap-2.5 text-sm text-ink">
              <input
                type="checkbox"
                checked={blind}
                onChange={(event) => setBlind(event.target.checked)}
                className="mt-1 size-4 accent-brand-700"
              />
              <span>
                إخفاء الرصيد الحالي أثناء العد
                <span className="block text-xs text-ink-muted">
                  يظهر رصيد كل صنف بعد إدخال عدّه فقط، حتى لا يُنسخ من الشاشة.
                </span>
              </span>
            </label>
            <button type="button" onClick={() => void onStart()} disabled={starting} className={buttonClass("primary")}>
              {starting ? "جارٍ البدء…" : "بدء الجرد"}
            </button>
          </CardContent>
        </Card>
      )}

      {failed ? <LoadError message={failed} onRetry={load} /> : null}

      <Card className="overflow-hidden">
        {items === null && !failed ? (
          <SkeletonRows rows={3} />
        ) : items && items.length === 0 ? (
          <EmptyState
            icon={ClipboardCheck}
            title="لا يوجد جرد سابق"
            body="بعد أول جرد يظهر هنا سجل ما عُدّ وما اعتُمد."
          />
        ) : (
          <ul className="divide-y divide-line">
            {items?.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-ink">{row.name}</p>
                  <p className="text-xs text-ink-muted">
                    {formatDateTime(row.created_at)}، عُدّ {row.counted_lines} من {row.total_lines}
                  </p>
                </div>
                <Badge variant={STATUS_VARIANT[row.status]}>{STATUS_LABELS[row.status]}</Badge>
                {row.status === "open" ? (
                  <Link href={`/inventory/stocktake/${row.id}`} className={buttonClass("secondary", "sm")}>
                    متابعة
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
