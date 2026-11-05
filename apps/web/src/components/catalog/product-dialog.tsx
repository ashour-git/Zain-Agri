"use client";

import { Loader2, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import { Field, FormError, FormNotice, SelectField, TextareaField } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { formatQuantity } from "@/lib/catalog";
import type {
  Brand,
  Category,
  ProductDetail,
  UnitConversion,
  UnitOfMeasure,
} from "@/lib/types";

type FormState = {
  name_ar: string;
  name: string;
  sku: string;
  barcode: string;
  description: string;
  category_id: string;
  brand_id: string;
  base_unit_id: string;
  sale_price: string;
  cost_price: string;
  minimum_stock: string;
  tracks_batches: boolean;
};

function emptyForm(units: UnitOfMeasure[]): FormState {
  return {
    name_ar: "",
    name: "",
    sku: "",
    barcode: "",
    description: "",
    category_id: "",
    brand_id: "",
    base_unit_id: units[0]?.id ?? "",
    sale_price: "",
    cost_price: "",
    minimum_stock: "0",
    tracks_batches: false,
  };
}

function fromProduct(product: ProductDetail, canSetCost: boolean): FormState {
  return {
    name_ar: product.name_ar,
    name: product.name ?? "",
    sku: product.sku,
    barcode: product.barcode ?? "",
    description: product.description ?? "",
    category_id: product.category_id ?? "",
    brand_id: product.brand_id ?? "",
    base_unit_id: product.base_unit_id,
    sale_price: product.sale_price ?? "",
    cost_price: canSetCost ? (product.cost_price ?? "") : "",
    minimum_stock: product.minimum_stock,
    tracks_batches: product.tracks_batches,
  };
}

function initialDraft(
  product: ProductDetail | null,
  units: UnitOfMeasure[],
): { from: string; to: string; factor: string } {
  if (!product) return { from: "", to: "", factor: "1" };
  const base = product.base_unit_id;
  const dimension = units.find((unit) => unit.id === base)?.dimension;
  const other = units.find((unit) => unit.id !== base && unit.dimension === dimension);
  return { from: base, to: other?.id ?? "", factor: "1" };
}

export function ProductDialog({
  product,
  units,
  categories,
  brands,
  canSetCost,
  onClose,
  onSaved,
}: {
  product: ProductDetail | null;
  units: UnitOfMeasure[];
  categories: Category[];
  brands: Brand[];
  canSetCost: boolean;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [form, setForm] = useState<FormState>(() =>
    product ? fromProduct(product, canSetCost) : emptyForm(units),
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [conversions, setConversions] = useState<UnitConversion[]>(product?.conversions ?? []);
  const [conversionError, setConversionError] = useState<string | null>(null);
  const [conversionPending, setConversionPending] = useState(false);
  const [conversionDraft, setConversionDraft] = useState(() => initialDraft(product, units));

  const baseUnit = units.find((unit) => unit.id === form.base_unit_id);
  const conversionUnitOptions = useMemo(
    () =>
      units.filter((unit) => unit.id !== form.base_unit_id && unit.dimension === baseUnit?.dimension),
    [units, form.base_unit_id, baseUnit?.dimension],
  );

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const submit = async () => {
    setError(null);
    if (!form.name_ar.trim() || !form.sku.trim() || !form.base_unit_id) {
      setError("الاسم العربي ورمز المنتج والوحدة الأساسية مطلوبة.");
      return;
    }

    const payload: Record<string, unknown> = {
      sku: form.sku.trim(),
      name_ar: form.name_ar.trim(),
      name: form.name.trim() || null,
      barcode: form.barcode.trim() || null,
      description: form.description.trim() || null,
      category_id: form.category_id || null,
      brand_id: form.brand_id || null,
      base_unit_id: form.base_unit_id,
      sale_price: form.sale_price === "" ? null : form.sale_price,
      minimum_stock: form.minimum_stock === "" ? "0" : form.minimum_stock,
      tracks_batches: form.tracks_batches,
    };
    if (canSetCost) payload.cost_price = form.cost_price === "" ? null : form.cost_price;

    setPending(true);
    try {
      if (product) {
        await apiRequest<ProductDetail>(`/api/v1/products/${product.id}`, {
          method: "PATCH",
          body: payload,
        });
        onSaved("تم تحديث المنتج.");
      } else {
        await apiRequest<ProductDetail>("/api/v1/products", { method: "POST", body: payload });
        onSaved("تم إضافة المنتج.");
      }
      onClose();
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError ? caught.message : "تعذّر حفظ المنتج. حاول مرة أخرى.",
      );
    } finally {
      setPending(false);
    }
  };

  const addConversion = async () => {
    if (!product) return;
    setConversionError(null);
    if (!conversionDraft.from || !conversionDraft.to) {
      setConversionError("اختر الوحدتين.");
      return;
    }
    setConversionPending(true);
    try {
      const created = await apiRequest<UnitConversion>(
        `/api/v1/products/${product.id}/conversions`,
        {
          method: "POST",
          body: {
            from_unit_id: conversionDraft.from,
            to_unit_id: conversionDraft.to,
            factor: conversionDraft.factor,
          },
        },
      );
      setConversions((current) => [...current, created]);
      setConversionError(null);
    } catch (caught) {
      setConversionError(
        caught instanceof ApiRequestError ? caught.message : "تعذّر إضافة التحويل.",
      );
    } finally {
      setConversionPending(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      wide
      title={product ? `تعديل ${product.name_ar}` : "منتج جديد"}
      description="الأسعار والكميات تُخزَّن بدقة عشرية على الخادم. الوحدة الأساسية هي وحدة كل حركة مخزون."
    >
      <div className="space-y-4">
        <FormError>{error}</FormError>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label="الاسم بالعربية *"
            name="name_ar"
            value={form.name_ar}
            onChange={(event) => update("name_ar", event.target.value)}
            placeholder="بذور طماطم هجين"
          />
          <Field
            label="الاسم الإنجليزي"
            name="name"
            dir="ltr"
            value={form.name}
            onChange={(event) => update("name", event.target.value)}
            placeholder="Hybrid tomato seeds"
          />
          <Field
            label="رمز المنتج (SKU) *"
            name="sku"
            dir="ltr"
            value={form.sku}
            onChange={(event) => update("sku", event.target.value)}
            placeholder="TOM-001"
          />
          <Field
            label="الباركود"
            name="barcode"
            dir="ltr"
            value={form.barcode}
            onChange={(event) => update("barcode", event.target.value)}
            placeholder="6221031000001"
          />
          <SelectField
            label="الوحدة الأساسية *"
            name="base_unit_id"
            value={form.base_unit_id}
            onChange={(event) => update("base_unit_id", event.target.value)}
            disabled={Boolean(product && conversions.length > 0)}
            hint={
              product && conversions.length > 0
                ? "لا يمكن تغيير الوحدة الأساسية بعد إضافة تحويلات."
                : undefined
            }
          >
            {units.map((unit) => (
              <option key={unit.id} value={unit.id}>
                {unit.name_ar} ({unit.code})
              </option>
            ))}
          </SelectField>
          <SelectField
            label="التصنيف"
            name="category_id"
            value={form.category_id}
            onChange={(event) => update("category_id", event.target.value)}
          >
            <option value="">بدون تصنيف</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name_ar ?? category.name}
              </option>
            ))}
          </SelectField>
          <SelectField
            label="العلامة التجارية"
            name="brand_id"
            value={form.brand_id}
            onChange={(event) => update("brand_id", event.target.value)}
          >
            <option value="">بدون علامة</option>
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name_ar ?? brand.name}
              </option>
            ))}
          </SelectField>
          <Field
            label="سعر البيع"
            name="sale_price"
            inputMode="decimal"
            dir="ltr"
            value={form.sale_price}
            onChange={(event) => update("sale_price", event.target.value)}
            placeholder="25.00"
          />
          {canSetCost ? (
            <Field
              label="سعر التكلفة"
              name="cost_price"
              inputMode="decimal"
              dir="ltr"
              value={form.cost_price}
              onChange={(event) => update("cost_price", event.target.value)}
              placeholder="18.00"
              hint="مرئي للمالك فقط."
            />
          ) : null}
          <Field
            label="حد التنبيه للمخزون"
            name="minimum_stock"
            inputMode="decimal"
            dir="ltr"
            value={form.minimum_stock}
            onChange={(event) => update("minimum_stock", event.target.value)}
          />
          <label className="flex items-center gap-2 self-end rounded-xl border border-line bg-surface/60 px-3.5 py-2.5 text-xs text-ink">
            <input
              type="checkbox"
              checked={form.tracks_batches}
              onChange={(event) => update("tracks_batches", event.target.checked)}
              className="size-4 rounded border-line accent-brand-700"
            />
            تتبع الدفعات وتواريخ الصلاحية
          </label>
        </div>

        <TextareaField
          label="الوصف"
          name="description"
          value={form.description}
          onChange={(event) => update("description", event.target.value)}
          placeholder="ملاحظات تظهر في بطاقة المنتج."
        />

        {product ? (
          <section className="space-y-3 rounded-xl border border-line bg-surface/40 p-4">
            <div>
              <h3 className="text-xs font-semibold text-ink">تحويلات الوحدات</h3>
              <p className="mt-1 text-xs leading-relaxed text-ink-muted">
                كل تحويل يجب أن يشمل الوحدة الأساسية، ولا يتم استنتاج سلاسل تحويل.
              </p>
            </div>

            {conversions.length === 0 ? (
              <p className="text-xs text-ink-muted">لا توجد تحويلات بعد.</p>
            ) : (
              <ul className="space-y-1.5">
                {conversions.map((conversion) => (
                  <li key={conversion.id} className="rounded-lg bg-white px-3 py-2 text-xs text-ink">
                    1 {conversion.from_unit_code} = {formatQuantity(conversion.factor)}{" "}
                    {conversion.to_unit_code}
                  </li>
                ))}
              </ul>
            )}

            <FormError>{conversionError}</FormError>

            <div className="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto]">
              <SelectField
                label="من وحدة"
                name="conversion_from"
                value={conversionDraft.from}
                onChange={(event) =>
                  setConversionDraft((current) => ({ ...current, from: event.target.value }))
                }
              >
                <option value={form.base_unit_id}>{baseUnit?.name_ar ?? "الوحدة الأساسية"}</option>
                {conversionUnitOptions.map((unit) => (
                  <option key={unit.id} value={unit.id}>
                    {unit.name_ar}
                  </option>
                ))}
              </SelectField>
              <SelectField
                label="إلى وحدة"
                name="conversion_to"
                value={conversionDraft.to}
                onChange={(event) =>
                  setConversionDraft((current) => ({ ...current, to: event.target.value }))
                }
              >
                <option value={form.base_unit_id}>{baseUnit?.name_ar ?? "الوحدة الأساسية"}</option>
                {conversionUnitOptions.map((unit) => (
                  <option key={unit.id} value={unit.id}>
                    {unit.name_ar}
                  </option>
                ))}
              </SelectField>
              <Field
                label="المعامل"
                name="conversion_factor"
                dir="ltr"
                inputMode="decimal"
                value={conversionDraft.factor}
                onChange={(event) =>
                  setConversionDraft((current) => ({ ...current, factor: event.target.value }))
                }
              />
              <button
                type="button"
                onClick={() => void addConversion()}
                disabled={conversionPending || conversionDraft.from === conversionDraft.to}
                className="mt-5 inline-flex h-[42px] items-center justify-center gap-1.5 rounded-xl border border-line bg-white px-3 text-xs font-semibold text-brand-700 transition-colors hover:border-brand-300 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {conversionPending ? (
                  <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Plus className="size-3.5" aria-hidden="true" />
                )}
                إضافة
              </button>
            </div>
          </section>
        ) : (
          <FormNotice>بعد الحفظ يمكنك إضافة تحويلات الوحدات من نفس الشاشة.</FormNotice>
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
            disabled={pending}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-700 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
            {product ? "حفظ التعديلات" : "إضافة المنتج"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
