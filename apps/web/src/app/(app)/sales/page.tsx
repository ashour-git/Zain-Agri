"use client";

import { Minus, Plus, ShoppingCart, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { CustomerPicker } from "@/components/sales/customer-picker";
import { ProductSearch } from "@/components/sales/product-search";
import { buttonClass } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, selectClass } from "@/components/ui/data";
import { FormError, controlClass } from "@/components/ui/field";
import { FieldLabel } from "@/components/ui/info-tip";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatMoney, toNumber, unitFactor } from "@/lib/catalog";
import type { Customer } from "@/lib/customers";
import { getUnits } from "@/lib/reference";
import { createSale, newSaleKey, roundMoney } from "@/lib/sales";
import type { Product, ProductDetail, UnitOfMeasure } from "@/lib/types";
import { cn } from "@/lib/utils";

type CounterLine = {
  key: string;
  product: ProductDetail;
  unitId: string;
  quantity: string;
  /** Unit price as typed; only owner/manager can change it. */
  price: string;
  priceEdited: boolean;
};

const details = new Map<string, Promise<ProductDetail>>();
const loadDetail = (id: string) => {
  let hit = details.get(id);
  if (!hit) {
    hit = apiRequest<ProductDetail>(`/api/v1/products/${id}`);
    hit.catch(() => details.delete(id));
    details.set(id, hit);
  }
  return hit;
};

/** The listed price in a unit: base sale price × how many base units it holds. */
function listedPrice(product: ProductDetail, unitId: string): string {
  if (!product.sale_price) return "";
  const factor = unitFactor(unitId, product.base_unit_id, product.conversions);
  return factor > 0 ? roundMoney(toNumber(product.sale_price) * factor).toFixed(2) : "";
}

function unitOptions(product: ProductDetail): string[] {
  const ids = new Set([product.base_unit_id]);
  for (const conversion of product.conversions) {
    for (const id of [conversion.from_unit_id, conversion.to_unit_id]) {
      if (unitFactor(id, product.base_unit_id, product.conversions) > 0) ids.add(id);
    }
  }
  return [...ids];
}

const lineTotal = (line: CounterLine) => roundMoney(toNumber(line.quantity) * toNumber(line.price));

export default function CounterPage() {
  const { session } = useAuth();
  const router = useRouter();
  const permissions = session?.permissions ?? [];
  const canSell = permissions.includes("sales.operate");
  const canDiscount = permissions.includes("sales.discount");

  const [units, setUnits] = useState<Map<string, UnitOfMeasure>>(new Map());
  const [lines, setLines] = useState<CounterLine[]>([]);
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [discount, setDiscount] = useState("");
  const [paid, setPaid] = useState("");
  const [saleKey, setSaleKey] = useState(newSaleKey);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getUnits()
      .then((list) => setUnits(new Map(list.map((unit) => [unit.id, unit]))))
      .catch(() => undefined);
  }, []);

  const subtotal = useMemo(() => roundMoney(lines.reduce((sum, line) => sum + lineTotal(line), 0)), [lines]);
  const discountValue = canDiscount ? roundMoney(toNumber(discount)) : 0;
  const total = roundMoney(Math.max(subtotal - discountValue, 0));
  const paidValue = customer && paid.trim() !== "" ? roundMoney(toNumber(paid)) : total;
  const credit = roundMoney(total - paidValue);

  const missingPrice = lines.find((line) => line.price.trim() === "");
  const problem =
    lines.length === 0
      ? null
      : missingPrice
        ? canDiscount
          ? `اكتب سعر «${missingPrice.product.name_ar}».`
          : `لا يوجد سعر بيع لـ«${missingPrice.product.name_ar}». اطلب من المالك تحديده.`
        : lines.some((line) => toNumber(line.quantity) <= 0)
          ? "كل صنف يحتاج كمية أكبر من صفر."
          : discountValue > subtotal
            ? "الخصم أكبر من قيمة الفاتورة."
            : paidValue > total
              ? "المدفوع أكبر من الإجمالي. سجّل الزيادة كتحصيل من صفحة العميل."
              : paidValue < 0
                ? "المدفوع لا يكون بالسالب."
                : null;

  const addProduct = async (product: Product) => {
    setError(null);
    try {
      const detail = await loadDetail(product.id);
      const preferred = detail.sale_unit_id ?? detail.base_unit_id;
      const unitId = unitOptions(detail).includes(preferred) ? preferred : detail.base_unit_id;
      setLines((current) => {
        const same = current.find((line) => line.product.id === detail.id && line.unitId === unitId);
        if (same) {
          return current.map((line) =>
            line === same ? { ...line, quantity: String(toNumber(line.quantity) + 1) } : line,
          );
        }
        return [
          ...current,
          {
            key: crypto.randomUUID(),
            product: detail,
            unitId,
            quantity: "1",
            price: listedPrice(detail, unitId),
            priceEdited: false,
          },
        ];
      });
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل الصنف.");
    }
  };

  const update = (key: string, change: Partial<CounterLine>) =>
    setLines((current) =>
      current.map((line) => {
        if (line.key !== key) return line;
        const next = { ...line, ...change };
        if (change.unitId && !next.priceEdited) next.price = listedPrice(next.product, change.unitId);
        return next;
      }),
    );

  const onSave = async () => {
    if (problem || lines.length === 0) return;
    setSaving(true);
    setError(null);
    try {
      const sale = await createSale({
        customer_id: customer?.id ?? null,
        discount: discountValue.toFixed(2),
        paid: customer ? paidValue.toFixed(2) : undefined,
        idempotency_key: saleKey,
        lines: lines.map((line) => ({
          product_id: line.product.id,
          quantity: line.quantity,
          unit_id: line.unitId === line.product.base_unit_id ? undefined : line.unitId,
          unit_price: line.priceEdited || !line.product.sale_price ? line.price : undefined,
        })),
      });
      setSaleKey(newSaleKey());
      router.push(`/sales/${sale.id}?saved=1`);
    } catch (caught) {
      if (caught instanceof ApiRequestError) {
        const name = (caught.details as { product_name?: string } | undefined)?.product_name;
        setError(name ? `${caught.message} (${name})` : caught.message);
      } else {
        setError("تعذّر حفظ الفاتورة. تحقق من الاتصال ثم اضغط حفظ مرة أخرى؛ لن تتكرر الفاتورة.");
      }
      setSaving(false);
    }
  };

  if (!canSell) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <FormError>ليست لديك صلاحية البيع. اطلبها من مالك المتجر.</FormError>
      </div>
    );
  }

  return (
    <div className="mx-auto grid w-full max-w-6xl gap-5 px-4 py-6 sm:px-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-lg font-bold text-ink">فاتورة جديدة</h1>
          <Link href="/sales/history" className={buttonClass("ghost", "sm")}>
            الفواتير السابقة
          </Link>
        </div>
        <ProductSearch onPick={(product) => void addProduct(product)} />

        <Card className="overflow-hidden">
          {lines.length === 0 ? (
            <EmptyState
              icon={ShoppingCart}
              title="الفاتورة فارغة"
              body="ابحث عن صنف بالاسم أو امسح الباركود، وسيُضاف هنا. اختياره مرة أخرى يزيد الكمية."
            />
          ) : (
            <ul className="divide-y divide-line">
              {lines.map((line) => {
                const options = unitOptions(line.product);
                return (
                  <li key={line.key} className="grid gap-3 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-ink">{line.product.name_ar}</p>
                      <p className="text-xs text-ink-muted">
                        الإجمالي <span className="font-medium tabular-nums text-ink">{formatMoney(lineTotal(line).toFixed(2))}</span>
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <div className="flex items-center rounded-md border border-line-strong">
                        <button
                          type="button"
                          aria-label={`إنقاص كمية ${line.product.name_ar}`}
                          onClick={() => update(line.key, { quantity: String(Math.max(toNumber(line.quantity) - 1, 0)) })}
                          className="grid size-10 place-items-center text-ink-muted hover:text-ink"
                        >
                          <Minus className="size-4" aria-hidden="true" />
                        </button>
                        <input
                          inputMode="decimal"
                          aria-label={`كمية ${line.product.name_ar}`}
                          value={line.quantity}
                          onChange={(event) => update(line.key, { quantity: event.target.value })}
                          className="h-10 w-16 border-x border-line text-center text-sm tabular-nums outline-none focus:bg-brand-50"
                        />
                        <button
                          type="button"
                          aria-label={`زيادة كمية ${line.product.name_ar}`}
                          onClick={() => update(line.key, { quantity: String(toNumber(line.quantity) + 1) })}
                          className="grid size-10 place-items-center text-ink-muted hover:text-ink"
                        >
                          <Plus className="size-4" aria-hidden="true" />
                        </button>
                      </div>
                      {options.length > 1 ? (
                        <select
                          aria-label={`وحدة ${line.product.name_ar}`}
                          value={line.unitId}
                          onChange={(event) => update(line.key, { unitId: event.target.value })}
                          className={cn(selectClass, "w-28")}
                        >
                          {options.map((id) => (
                            <option key={id} value={id}>
                              {units.get(id)?.name_ar ?? (id === line.product.base_unit_id ? line.product.base_unit_name_ar : "وحدة")}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className="w-16 text-sm text-ink-muted">{line.product.base_unit_name_ar}</span>
                      )}
                      <label className="flex items-center gap-1.5 text-xs text-ink-muted">
                        <span className="sr-only">سعر الوحدة لـ{line.product.name_ar}</span>
                        <input
                          inputMode="decimal"
                          readOnly={!canDiscount}
                          value={line.price}
                          placeholder={canDiscount ? "السعر" : "بلا سعر"}
                          onChange={(event) => update(line.key, { price: event.target.value, priceEdited: true })}
                          className={cn(controlClass, "w-24 tabular-nums", !canDiscount && "bg-surface text-ink-muted")}
                        />
                        ج.م
                      </label>
                      <button
                        type="button"
                        aria-label={`حذف ${line.product.name_ar} من الفاتورة`}
                        onClick={() => setLines((current) => current.filter((row) => row.key !== line.key))}
                        className={buttonClass("ghost", "sm")}
                      >
                        <Trash2 className="size-4" aria-hidden="true" />
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
        <Card>
          <CardHeader>
            <CardTitle>العميل</CardTitle>
          </CardHeader>
          <CardContent>
            <CustomerPicker
              customer={customer}
              onChange={(picked) => {
                setCustomer(picked);
                setPaid("");
              }}
            />
          </CardContent>
        </Card>

        <Card>
          <CardContent className="space-y-3 pt-5">
            <dl className="space-y-1.5 text-sm">
              <div className="flex justify-between">
                <dt className="text-ink-muted">المجموع</dt>
                <dd className="tabular-nums">{formatMoney(subtotal.toFixed(2))}</dd>
              </div>
            </dl>
            {canDiscount ? (
              <div className="space-y-1.5">
                <FieldLabel
                  htmlFor="sale-discount"
                  label="خصم على الفاتورة"
                  info="مبلغ يُطرح من إجمالي الفاتورة كلها. اتركه فارغًا لو مفيش خصم."
                />
                <input
                  id="sale-discount"
                  inputMode="decimal"
                  value={discount}
                  onChange={(event) => setDiscount(event.target.value)}
                  placeholder="0"
                  className={cn(controlClass, "tabular-nums")}
                />
              </div>
            ) : null}
            <div className="flex items-baseline justify-between border-t border-line pt-3">
              <span className="text-sm font-semibold text-ink">الإجمالي</span>
              <span className="text-xl font-bold tabular-nums text-brand-800">{formatMoney(total.toFixed(2))}</span>
            </div>
            {customer ? (
              <div className="space-y-1.5">
                <FieldLabel
                  htmlFor="sale-paid"
                  label="المدفوع الآن"
                  info="اكتب ما دفعه العميل الآن. الباقي يُسجَّل عليه آجل في حسابه. اتركه فارغًا لو دفع الكل."
                />
                <input
                  id="sale-paid"
                  inputMode="decimal"
                  value={paid}
                  onChange={(event) => setPaid(event.target.value)}
                  placeholder={total.toFixed(2)}
                  className={cn(controlClass, "tabular-nums")}
                />
                {credit > 0 ? (
                  <p className="text-sm text-red-700">
                    يُسجَّل عليه آجل: <span className="font-semibold tabular-nums">{formatMoney(credit.toFixed(2))}</span>
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="text-xs text-ink-muted">الزبون النقدي يدفع المبلغ كاملًا. للبيع بالآجل اختر عميلًا.</p>
            )}
            <FormError>{error ?? problem}</FormError>
            <button
              type="button"
              onClick={() => void onSave()}
              disabled={saving || lines.length === 0 || problem !== null}
              className={buttonClass("primary", "md", "min-h-12 w-full text-base")}
            >
              {saving ? "جارٍ الحفظ…" : "حفظ الفاتورة"}
            </button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
