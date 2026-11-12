"use client";

import { Check, ClipboardCheck, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import {
  EmptyState,
  LoadError,
  Pagination,
  SearchBox,
  Segmented,
  SkeletonRows,
  selectClass,
} from "@/components/ui/data";
import { FormError, FormNotice } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatQuantity } from "@/lib/catalog";
import { getUnits } from "@/lib/reference";
import {
  REASON_LABELS,
  type Review,
  type ReviewItem,
  type ShortageReason,
  type Stocktake,
  type StocktakeLine,
  applyStocktake,
  cancelStocktake,
  countLine,
  getLines,
  getReview,
  getStocktake,
} from "@/lib/stocktake";
import type { UnitOfMeasure } from "@/lib/types";
import { cn } from "@/lib/utils";

type View = "count" | "review";

const message = (caught: unknown, fallback: string) =>
  caught instanceof ApiRequestError ? caught.message : fallback;

function CountRow({
  line,
  units,
  stocktakeId,
  blind,
  onSaved,
}: {
  line: StocktakeLine;
  units: UnitOfMeasure[];
  stocktakeId: string;
  blind: boolean;
  onSaved: (line: StocktakeLine) => void;
}) {
  const counted = line.counted_quantity !== null;
  const [value, setValue] = useState(line.counted_quantity ?? "");
  const [unitId, setUnitId] = useState(line.counted_unit_id ?? line.base_unit_id);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const baseUnit = units.find((unit) => unit.id === line.base_unit_id);
  const sameFamily = units.filter((unit) => baseUnit && unit.dimension === baseUnit.dimension);

  const save = async () => {
    const trimmed = value.trim();
    if (trimmed === "" || Number.isNaN(Number(trimmed)) || Number(trimmed) < 0) {
      setError("أدخل كمية صحيحة، ويمكن أن تكون صفرًا.");
      return;
    }
    if (counted && trimmed === line.counted_quantity && unitId === (line.counted_unit_id ?? line.base_unit_id)) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await countLine(stocktakeId, line.line_id, { quantity: trimmed, unit_id: unitId }));
    } catch (caught) {
      setError(message(caught, "تعذّر حفظ العدّ. حاول مرة أخرى."));
    } finally {
      setSaving(false);
    }
  };

  const difference =
    counted && line.system_quantity !== null && line.counted_base_quantity !== null
      ? Number(line.counted_base_quantity) - Number(line.system_quantity)
      : null;

  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-ink">{line.name_ar}</p>
          <p className="text-xs text-ink-muted" dir="ltr">
            {line.sku}
            {line.batch_number ? `  /  ${line.batch_number}` : ""}
          </p>
        </div>
        {counted ? (
          <Badge variant="brand">
            <Check className="size-3" aria-hidden="true" />
            عُدّ
          </Badge>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          inputMode="decimal"
          dir="ltr"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onBlur={() => void save()}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              (event.target as HTMLInputElement).blur();
            }
          }}
          aria-label={`الكمية المعدودة من ${line.name_ar}`}
          placeholder="0"
          className={cn(selectClass, "h-11 w-28 text-center text-base tabular-nums")}
        />
        <select
          value={unitId}
          onChange={(event) => setUnitId(event.target.value)}
          onBlur={() => void save()}
          aria-label="وحدة العدّ"
          className={cn(selectClass, "h-11 w-auto min-w-24")}
        >
          {(sameFamily.length > 0 ? sameFamily : [{ id: line.base_unit_id, name_ar: line.base_unit_name_ar }]).map(
            (unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name_ar}
              </option>
            ),
          )}
        </select>
        {saving ? <Loader2 className="size-4 animate-spin text-ink-muted" aria-label="جارٍ الحفظ" /> : null}
        {counted && line.system_quantity !== null ? (
          <span className="text-xs text-ink-muted">
            الرصيد وقت العدّ: {formatQuantity(line.system_quantity)} {line.base_unit_name_ar}
            {difference !== null && difference !== 0 ? (
              <bdi className={difference < 0 ? "ms-2 text-red-700" : "ms-2 text-brand-700"} dir="ltr">
                {`${difference > 0 ? "+" : "-"}${formatQuantity(String(Math.abs(difference)))}`}
              </bdi>
            ) : null}
          </span>
        ) : !blind && line.system_quantity !== null ? (
          <span className="text-xs text-ink-muted">
            الرصيد الحالي: {formatQuantity(line.system_quantity)} {line.base_unit_name_ar}
          </span>
        ) : null}
      </div>
      {error ? <p className="text-xs text-red-700">{error}</p> : null}
    </li>
  );
}

function ReviewRow({
  item,
  stocktakeId,
  units,
  lineUnit,
  onChanged,
}: {
  item: ReviewItem;
  stocktakeId: string;
  units: UnitOfMeasure[];
  lineUnit: string | undefined;
  onChanged: () => void;
}) {
  const [saving, setSaving] = useState(false);
  const shortage = Number(item.difference) < 0;
  void units;

  const changeReason = async (reason: ShortageReason) => {
    setSaving(true);
    try {
      await countLine(stocktakeId, item.line_id, {
        quantity: item.counted_base_quantity,
        unit_id: lineUnit,
        shortage_reason: reason,
      });
      onChanged();
    } finally {
      setSaving(false);
    }
  };

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
      <div className="min-w-0 flex-1 basis-48">
        <p className="text-sm font-medium text-ink">{item.name_ar}</p>
        <p className="text-xs text-ink-muted">
          {item.batch_number ? `دفعة ${item.batch_number}، ` : ""}
          الرصيد {formatQuantity(item.system_quantity_at_count)} والمعدود{" "}
          {formatQuantity(item.counted_base_quantity)} {item.base_unit_name_ar}
        </p>
      </div>
      <bdi
        className={cn("text-base font-semibold tabular-nums", shortage ? "text-red-700" : "text-brand-700")}
        dir="ltr"
      >
        {`${shortage ? "-" : "+"}${formatQuantity(String(Math.abs(Number(item.difference))))}`}
      </bdi>
      {shortage ? (
        <select
          value={item.shortage_reason}
          onChange={(event) => void changeReason(event.target.value as ShortageReason)}
          disabled={saving}
          aria-label={`سبب العجز في ${item.name_ar}`}
          className={cn(selectClass, "w-auto min-w-32")}
        >
          {(Object.keys(REASON_LABELS) as ShortageReason[]).map((reason) => (
            <option key={reason} value={reason}>
              {REASON_LABELS[reason]}
            </option>
          ))}
        </select>
      ) : null}
    </li>
  );
}

export default function StocktakePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { session } = useAuth();
  const canCount = session?.permissions.includes("inventory.adjust") ?? false;

  const [stocktake, setStocktake] = useState<Stocktake | null>(null);
  const [units, setUnits] = useState<UnitOfMeasure[]>([]);
  const [view, setView] = useState<View>("count");
  const [lines, setLines] = useState<StocktakeLine[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [onlyUncounted, setOnlyUncounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState<"apply" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isOpen = stocktake?.status === "open";

  const loadHeader = useCallback(() => {
    getStocktake(id)
      .then(setStocktake)
      .catch((caught: unknown) => setFailed(message(caught, "تعذّر تحميل الجرد.")));
  }, [id]);

  const loadLines = useCallback(() => {
    getLines(id, { q: search, onlyUncounted, page })
      .then((result) => {
        setFailed(null);
        setLines(result.items);
        setTotal(result.total);
      })
      .catch((caught: unknown) => setFailed(message(caught, "تعذّر تحميل المنتجات.")))
      .finally(() => setLoading(false));
  }, [id, search, onlyUncounted, page]);

  const loadReview = useCallback(() => {
    getReview(id)
      .then(setReview)
      .catch((caught: unknown) => setError(message(caught, "تعذّر تحميل الفروق.")));
  }, [id]);

  useEffect(() => {
    if (!canCount) return;
    loadHeader();
    void getUnits().then(setUnits).catch(() => setUnits([]));
  }, [canCount, loadHeader]);

  useEffect(() => {
    if (canCount && view === "count") loadLines();
  }, [canCount, view, loadLines]);

  useEffect(() => {
    if (canCount && view === "review") loadReview();
  }, [canCount, view, loadReview]);

  const lineUnits = useMemo(() => {
    const map = new Map<string, string>();
    for (const line of lines) map.set(line.line_id, line.counted_unit_id ?? line.base_unit_id);
    return map;
  }, [lines]);

  if (!canCount) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <FormError>ليست لديك صلاحية الجرد. اطلبها من مالك المتجر.</FormError>
      </div>
    );
  }

  const saved = (line: StocktakeLine) => {
    setLines((current) => current.map((row) => (row.line_id === line.line_id ? line : row)));
    loadHeader();
  };

  const apply = async () => {
    setBusy("apply");
    setError(null);
    try {
      const result = await applyStocktake(id);
      router.replace(`/inventory/stocktake?done=${result.corrections}`);
    } catch (caught) {
      setConfirmOpen(false);
      const details = caught instanceof ApiRequestError ? (caught.details as { product_name?: string } | undefined) : undefined;
      setError(
        details?.product_name
          ? `${message(caught, "تعذّر اعتماد الجرد.")} الصنف: ${details.product_name}`
          : message(caught, "تعذّر اعتماد الجرد."),
      );
      setBusy(null);
    }
  };

  const cancel = async () => {
    setBusy("cancel");
    setError(null);
    try {
      await cancelStocktake(id);
      router.replace("/inventory/stocktake");
    } catch (caught) {
      setError(message(caught, "تعذّر إلغاء الجرد."));
      setBusy(null);
    }
  };

  const corrections = review ? review.shortages.length + review.surpluses.length : 0;
  const totalPages = Math.max(1, Math.ceil(total / 50));

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-4 py-6 sm:px-8">
      <PageHeader
        title={stocktake?.name ?? "الجرد"}
        description={
          stocktake
            ? `عُدّ ${stocktake.counted_lines} من ${stocktake.total_lines}${isOpen ? "" : "، الجرد مغلق"}`
            : undefined
        }
        actions={
          <Link href="/inventory/stocktake" className={buttonClass("ghost", "sm")}>
            كل عمليات الجرد
          </Link>
        }
      />

      <FormError>{error}</FormError>

      {stocktake && !isOpen ? (
        <FormNotice>{`هذا الجرد ${stocktake.status === "applied" ? "معتمد" : "ملغى"} ولا يمكن تعديله.`}</FormNotice>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Segmented<View>
          label="عرض الجرد"
          value={view}
          options={[
            { id: "count", label: "العدّ" },
            { id: "review", label: "مراجعة الفروق" },
          ]}
          onChange={setView}
        />
        {isOpen ? (
          <button
            type="button"
            onClick={() => void cancel()}
            disabled={busy !== null}
            className={buttonClass("danger", "sm", "ms-auto")}
          >
            {busy === "cancel" ? "جارٍ الإلغاء…" : "إلغاء الجرد"}
          </button>
        ) : null}
      </div>

      {view === "count" ? (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <SearchBox
              value={query}
              onChange={setQuery}
              onSubmit={() => {
                setPage(1);
                setSearch(query.trim());
              }}
              label="بحث في الجرد"
              placeholder="اسم المنتج أو الرمز أو الباركود"
            />
            <label className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={onlyUncounted}
                onChange={(event) => {
                  setPage(1);
                  setOnlyUncounted(event.target.checked);
                }}
                className="size-4 accent-brand-700"
              />
              غير المعدود فقط
            </label>
          </div>

          {failed ? <LoadError message={failed} onRetry={loadLines} /> : null}

          <Card className="overflow-hidden">
            {loading && lines.length === 0 ? (
              <SkeletonRows />
            ) : lines.length === 0 && !failed ? (
              <EmptyState
                icon={ClipboardCheck}
                title={search || onlyUncounted ? "لا توجد نتائج" : "لا توجد منتجات في هذا الجرد"}
                body={
                  search || onlyUncounted
                    ? "غيّر البحث أو ألغِ فلتر غير المعدود."
                    : "أضف منتجات وسجّل رصيدها، ثم ابدأ جردًا جديدًا."
                }
              />
            ) : (
              <ul className="divide-y divide-line">
                {lines.map((line) =>
                  isOpen ? (
                    <CountRow
                      key={line.line_id}
                      line={line}
                      units={units}
                      stocktakeId={id}
                      blind={stocktake?.blind ?? true}
                      onSaved={saved}
                    />
                  ) : (
                    <li key={line.line_id} className="flex justify-between gap-3 px-4 py-3 text-sm">
                      <span>{line.name_ar}</span>
                      <span className="tabular-nums text-ink-muted">
                        {line.counted_quantity === null ? "لم يُعدّ" : formatQuantity(line.counted_quantity)}
                      </span>
                    </li>
                  ),
                )}
              </ul>
            )}
          </Card>

          <Pagination page={page} totalPages={totalPages} total={total} noun="منتج" onChange={setPage} />

          {isOpen ? (
            <div className="sticky bottom-0 -mx-4 border-t border-line bg-surface/95 px-4 py-3 sm:mx-0 sm:rounded-md sm:border">
              <button type="button" onClick={() => setView("review")} className={cn(buttonClass("primary"), "w-full sm:w-auto")}>
                مراجعة الفروق
              </button>
            </div>
          ) : null}
        </>
      ) : review === null ? (
        <SkeletonRows rows={4} />
      ) : (
        <div className="space-y-5">
          <p className="text-sm text-ink-muted">
            {corrections === 0
              ? "لا توجد فروق: كل ما عُدّ يطابق الرصيد."
              : `سيُسجَّل ${corrections} تصحيح عند الاعتماد. الأصناف غير المعدودة (${review.uncounted.length}) لا تتغير أبدًا.`}
          </p>

          {(
            [
              ["العجز", review.shortages],
              ["الزيادة", review.surpluses],
            ] as const
          ).map(([title, rows]) =>
            rows.length > 0 ? (
              <section key={title} className="space-y-2">
                <h3 className="text-[15px] font-semibold text-ink">
                  {title} ({rows.length})
                </h3>
                <Card className="overflow-hidden">
                  <ul className="divide-y divide-line">
                    {rows.map((item) => (
                      <ReviewRow
                        key={item.line_id}
                        item={item}
                        stocktakeId={id}
                        units={units}
                        lineUnit={lineUnits.get(item.line_id)}
                        onChanged={loadReview}
                      />
                    ))}
                  </ul>
                </Card>
              </section>
            ) : null,
          )}

          {review.uncounted.length > 0 ? (
            <section className="space-y-2">
              <h3 className="text-[15px] font-semibold text-ink">لم تُعدّ ({review.uncounted.length})</h3>
              <Card className="max-h-64 overflow-y-auto">
                <ul className="divide-y divide-line text-sm text-ink-muted">
                  {review.uncounted.map((row) => (
                    <li key={row.line_id} className="px-4 py-2">
                      {row.name_ar}
                      {row.batch_number ? ` (${row.batch_number})` : ""}
                    </li>
                  ))}
                </ul>
              </Card>
            </section>
          ) : null}

          {isOpen ? (
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" onClick={() => setView("count")} className={buttonClass("secondary")}>
                العودة للعدّ
              </button>
              <button
                type="button"
                onClick={() => setConfirmOpen(true)}
                disabled={busy !== null || corrections === 0}
                className={buttonClass("primary")}
              >
                اعتماد الجرد
              </button>
            </div>
          ) : null}
        </div>
      )}

      <Modal
        open={confirmOpen}
        title="اعتماد الجرد"
        description={`سيُسجَّل ${corrections} تصحيح على المخزون دفعة واحدة، ولا يمكن التراجع عنه بعد الاعتماد.`}
        onClose={() => setConfirmOpen(false)}
      >
        <div className="flex flex-wrap gap-3">
          <button type="button" onClick={() => void apply()} disabled={busy !== null} className={buttonClass("primary")}>
            {busy === "apply" ? "جارٍ الاعتماد…" : "تأكيد الاعتماد"}
          </button>
          <button type="button" onClick={() => setConfirmOpen(false)} className={buttonClass("secondary")}>
            رجوع
          </button>
        </div>
      </Modal>
    </div>
  );
}
