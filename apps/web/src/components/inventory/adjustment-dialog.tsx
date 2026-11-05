"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Field, FormError, SelectField, TextareaField } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError, apiRequest } from "@/lib/api";
import {
  MOVEMENT_LABELS,
  WRITABLE_MOVEMENTS,
  formatDate,
  formatQuantity,
  isInbound,
  toNumber,
  unitFactor,
} from "@/lib/catalog";
import type {
  AdjustmentResult,
  Batch,
  BatchList,
  InventoryItem,
  MovementType,
  ProductDetail,
  UnitOfMeasure,
} from "@/lib/types";

export function AdjustmentDialog({
  products,
  initialProductId,
  canSetCost,
  units,
  onClose,
  onSaved,
}: {
  products: InventoryItem[];
  initialProductId: string | null;
  canSetCost: boolean;
  units: UnitOfMeasure[];
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [productId, setProductId] = useState(initialProductId ?? "");
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);

  const [movementType, setMovementType] = useState<MovementType>("opening_balance");
  const [quantity, setQuantity] = useState("");
  const [unitId, setUnitId] = useState("");
  const [batchId, setBatchId] = useState("");
  const [reason, setReason] = useState("");
  const [unitCost, setUnitCost] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!productId) return;
    let cancelled = false;

    void Promise.all([
      apiRequest<ProductDetail>(`/api/v1/products/${productId}`),
      apiRequest<BatchList>(`/api/v1/inventory/batches?product_id=${productId}&page_size=100`),
    ])
      .then(([productDetail, batchRows]) => {
        if (cancelled) return;
        setDetail(productDetail);
        setBatches(batchRows.items);
        setUnitId(productDetail.base_unit_id);
        setDetailError(null);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setDetail(null);
        setDetailError(
          caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل بيانات المنتج.",
        );
      });

    return () => {
      cancelled = true;
    };
  }, [productId]);

  const loading = Boolean(productId) && !detail && !detailError;

  const selected = products.find((row) => row.product_id === productId);
  const balance = detail?.stock_quantity ?? selected?.quantity ?? "0";
  const baseUnitId = detail?.base_unit_id ?? selected?.base_unit_id ?? "";
  const tracksBatches = detail?.tracks_batches ?? selected?.tracks_batches ?? false;

  const unitOptions = useMemo(() => {
    if (!detail) return units.filter((unit) => unit.id === baseUnitId);
    const ids = new Set<string>([detail.base_unit_id]);
    for (const conversion of detail.conversions) {
      ids.add(
        conversion.from_unit_id === detail.base_unit_id
          ? conversion.to_unit_id
          : conversion.from_unit_id,
      );
    }
    return units.filter((unit) => ids.has(unit.id));
  }, [detail, units, baseUnitId]);

  const factor = detail
    ? unitFactor(unitId || detail.base_unit_id, detail.base_unit_id, detail.conversions)
    : 0;
  const delta = toNumber(quantity) * factor * (isInbound(movementType) ? 1 : -1);
  const expected = toNumber(balance) + delta;
  const willGoNegative = expected < 0;

  const changeProduct = (value: string) => {
    setProductId(value);
    setDetail(null);
    setDetailError(null);
    setBatches([]);
    setBatchId("");
    setUnitId("");
    setError(null);
  };

  const submit = async () => {
    setError(null);
    if (!productId) {
      setError("اختر المنتج.");
      return;
    }
    if (!quantity || toNumber(quantity) <= 0) {
      setError("الكمية يجب أن تكون أكبر من صفر.");
      return;
    }
    if (reason.trim().length < 3) {
      setError("سبب الحركة مطلوب (3 أحرف على الأقل).");
      return;
    }
    if (tracksBatches && !batchId) {
      setError("هذا المنتج يتتبع الدفعات: اختر دفعة.");
      return;
    }
    if (willGoNegative) {
      setError("الرصيد الناتج سالب. عدّل الكمية أو النوع.");
      return;
    }

    setPending(true);
    try {
      const result = await apiRequest<AdjustmentResult>("/api/v1/inventory/adjustments", {
        method: "POST",
        body: {
          product_id: productId,
          movement_type: movementType,
          quantity,
          unit_id: unitId || baseUnitId,
          batch_id: tracksBatches ? batchId : null,
          reason: reason.trim(),
          ...(canSetCost && unitCost !== "" ? { unit_cost: unitCost } : {}),
        },
      });
      onSaved(
        `تم تسجيل الحركة. الرصيد: ${formatQuantity(result.balance_before)} ← ${formatQuantity(
          result.balance_after,
        )}.`,
      );
      onClose();
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError ? caught.message : "تعذّر تسجيل الحركة. حاول مرة أخرى.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      wide
      title="تسوية مخزون"
      description="الحركات لا تُعدَّل ولا تُحذف. أي تصحيح يكون بحركة معاكسة، والرصيد لا يمكن أن يصبح سالباً."
    >
      <div className="space-y-4">
        <FormError>{error}</FormError>

        <div className="grid gap-3 sm:grid-cols-2">
          <SelectField
            label="المنتج *"
            name="adjustment_product"
            value={productId}
            onChange={(event) => changeProduct(event.target.value)}
          >
            <option value="">اختر منتجاً</option>
            {products.map((product) => (
              <option key={product.product_id} value={product.product_id}>
                {product.name_ar} - {product.sku}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="نوع الحركة *"
            name="movement_type"
            value={movementType}
            onChange={(event) => setMovementType(event.target.value as MovementType)}
          >
            {WRITABLE_MOVEMENTS.map((type) => (
              <option key={type} value={type}>
                {MOVEMENT_LABELS[type]}
              </option>
            ))}
          </SelectField>

          <Field
            label="الكمية *"
            name="adjustment_quantity"
            dir="ltr"
            inputMode="decimal"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
            placeholder="10"
          />
          <SelectField
            label="الوحدة"
            name="adjustment_unit"
            value={unitId || baseUnitId}
            onChange={(event) => setUnitId(event.target.value)}
            disabled={loading || !detail}
            hint="التحويلات المتاحة لهذا المنتج فقط."
          >
            {unitOptions.map((unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name_ar} ({unit.code})
              </option>
            ))}
          </SelectField>

          {tracksBatches ? (
            <SelectField
              label="الدفعة *"
              name="adjustment_batch"
              value={batchId}
              onChange={(event) => setBatchId(event.target.value)}
              hint={
                batches.length === 0
                  ? "لا توجد دفعات لهذا المنتج بعد. أضف دفعة من شاشة المخزون أولاً."
                  : undefined
              }
            >
              <option value="">اختر دفعة</option>
              {batches.map((batch) => (
                <option key={batch.id} value={batch.id}>
                  {batch.batch_number}
                  {batch.expiry_date ? ` (تنتهي ${formatDate(batch.expiry_date)})` : ""}
                </option>
              ))}
            </SelectField>
          ) : null}

          {canSetCost && isInbound(movementType) ? (
            <Field
              label="تكلفة الوحدة الأساسية"
              name="adjustment_unit_cost"
              dir="ltr"
              inputMode="decimal"
              value={unitCost}
              onChange={(event) => setUnitCost(event.target.value)}
              placeholder="18.00"
              hint="تُسجَّل للاطلاع فقط؛ لا توجد طريقة تكلفة معتمدة بعد."
            />
          ) : null}
        </div>

        <TextareaField
          label="سبب الحركة *"
          name="adjustment_reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="جرد دوري، تالف، رصيد افتتاحي…"
        />

        <div className="grid gap-3 rounded-xl border border-line bg-surface/50 p-4 sm:grid-cols-3">
          <div>
            <p className="text-xs text-ink-muted">الرصيد الحالي</p>
            <p className="mt-0.5 text-sm font-semibold text-ink">{formatQuantity(balance)}</p>
          </div>
          <div>
            <p className="text-xs text-ink-muted">التغيير المتوقع</p>
            <p
              className={`mt-0.5 text-sm font-semibold ${delta < 0 ? "text-red-700" : "text-brand-700"}`}
              dir="ltr"
            >
              {delta > 0 ? "+" : ""}
              {formatQuantity(String(delta))}
            </p>
          </div>
          <div>
            <p className="text-xs text-ink-muted">الرصيد بعد التأكيد</p>
            <p className="mt-0.5 text-sm font-semibold text-ink">
              {formatQuantity(String(expected))}
            </p>
          </div>
        </div>

        {willGoNegative ? (
          <p className="flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-xs leading-relaxed text-red-700">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
            الرصيد الناتج سالب. سيرفض الخادم هذه الحركة.
          </p>
        ) : (
          <p className="text-xs leading-relaxed text-ink-muted">
            يُحفظ الرصيد الافتتاحي مرة واحدة لكل منتج؛ بعد ذلك استخدم تسوية بالزيادة أو النقص.
          </p>
        )}

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-line px-4 py-2 text-xs text-ink-muted transition-colors hover:text-ink"
          >
            إلغاء
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={pending || loading || !detail}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-700 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
            تأكيد الحركة
          </button>
        </div>
      </div>
    </Modal>
  );
}
