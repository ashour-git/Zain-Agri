"use client";

import { ArrowDownLeft, ArrowUpRight, Check, PackagePlus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { StockGauge } from "@/components/inventory/stock-gauge";
import { buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { MOVEMENT_LABELS, formatDateTime, formatQuantity } from "@/lib/catalog";
import type { InventoryItem, InventoryList, MovementList, ProductList } from "@/lib/types";
import { cn } from "@/lib/utils";

type Overview = {
  products: number | null;
  low: InventoryList | null;
  out: InventoryList | null;
  movements: MovementList | null;
};

const EMPTY: Overview = { products: null, low: null, out: null, movements: null };

/** A missing permission is not an error: that figure simply stays empty. */
function optional<T>(allowed: boolean, load: () => Promise<T>): Promise<T | null> {
  return allowed ? load().catch(() => null) : Promise.resolve(null);
}

function greeting(): string {
  return new Date().getHours() < 12 ? "صباح الخير" : "مساء الخير";
}

export default function DashboardPage() {
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const can = (permission: string) => permissions.includes(permission);
  const canProducts = can("products.read");
  const canInventory = can("inventory.read");
  const tenantId = session?.tenant?.id ?? "";

  const [overview, setOverview] = useState<{ key: string; data: Overview } | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const requestKey = `${tenantId}|${refreshKey}`;
  const loading = overview?.key !== requestKey;
  const data = overview?.data ?? EMPTY;

  useEffect(() => {
    let cancelled = false;
    void Promise.all([
      optional(canProducts, () =>
        apiRequest<ProductList>("/api/v1/products?status=active&page_size=1").then((r) => r.total),
      ),
      optional(canInventory, () => apiRequest<InventoryList>("/api/v1/inventory?stock=low&page_size=8")),
      optional(canInventory, () => apiRequest<InventoryList>("/api/v1/inventory?stock=out&page_size=8")),
      optional(canInventory, () => apiRequest<MovementList>("/api/v1/inventory/movements?page_size=8")),
    ]).then(([products, low, out, movements]) => {
      if (!cancelled) setOverview({ key: requestKey, data: { products, low, out, movements } });
    });
    return () => {
      cancelled = true;
    };
  }, [requestKey, canProducts, canInventory]);

  const reorder: InventoryItem[] = [...(data.out?.items ?? []), ...(data.low?.items ?? [])].slice(0, 8);
  const firstName = session?.user.full_name?.trim().split(/\s+/)[0] ?? "";
  const hasMovements = (data.movements?.total ?? 0) > 0;
  const setupPending = !loading && (data.products === 0 || (canInventory && !hasMovements));

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 sm:px-8 sm:py-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-ink-muted">
          {greeting()}
          {firstName ? ` يا ${firstName}` : ""}،{" "}
          {new Intl.DateTimeFormat("ar-EG-u-nu-latn", { weekday: "long", day: "numeric", month: "long" }).format(
            new Date(),
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setRefreshKey((current) => current + 1)}
            disabled={loading}
            className={buttonClass("ghost", "sm")}
          >
            <RefreshCw className={cn("size-4", loading && "animate-spin")} aria-hidden="true" />
            تحديث
          </button>
          {can("products.create") ? (
            <Link href="/products?new=1" className={buttonClass("primary", "sm")}>
              <PackagePlus className="size-4" aria-hidden="true" />
              منتج جديد
            </Link>
          ) : null}
        </div>
      </div>

      {/* One strip of figures divided by hairlines, read like the totals row of a sheet. */}
      <Card>
        <dl className="grid grid-cols-2 lg:grid-cols-4">
          <Figure
            className="border-b border-e border-line lg:border-b-0"
            label="منتجات نشطة"
            value={data.products}
            loading={loading && canProducts}
            href={canProducts ? "/products" : undefined}
          />
          <Figure
            className="border-b border-line lg:border-b-0 lg:border-e"
            label="تحت الحد الأدنى"
            value={data.low?.total ?? null}
            tone="warning"
            loading={loading && canInventory}
            href={canInventory ? "/inventory?stock=low" : undefined}
          />
          <Figure
            className="border-e border-line"
            label="نفدت"
            value={data.out?.total ?? null}
            tone="danger"
            loading={loading && canInventory}
            href={canInventory ? "/inventory?stock=out" : undefined}
          />
          <Figure label="مبيعات اليوم" value={null} note="تظهر بعد تفعيل نقطة البيع" />
        </dl>
      </Card>

      {setupPending && can("products.create") ? (
        <GettingStarted hasProducts={(data.products ?? 0) > 0} hasMovements={hasMovements} />
      ) : null}

      {canInventory && !(data.products === 0) ? (
        <div className="grid gap-6 lg:grid-cols-5">
          <Section
            className="lg:col-span-3"
            title="يحتاج إعادة طلب"
            action={
              <Link href="/inventory?stock=low" className="text-sm font-medium text-brand-700 hover:underline">
                كل المخزون
              </Link>
            }
          >
            {loading ? (
              <Rows />
            ) : reorder.length === 0 ? (
              <Empty>
                <Check className="mx-auto mb-2 size-5 text-brand-600" aria-hidden="true" />
                كل المنتجات فوق حدها الأدنى.
              </Empty>
            ) : (
              <ul className="divide-y divide-line">
                {reorder.map((item) => (
                  <li key={item.product_id} className="flex items-center gap-4 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-ink">{item.name_ar}</p>
                      <p className="text-xs text-ink-muted">
                        الحد الأدنى <span className="tabular">{formatQuantity(item.minimum_stock)}</span>{" "}
                        {item.base_unit_name_ar}
                      </p>
                    </div>
                    <StockGauge
                      className="w-32 shrink-0 sm:w-40"
                      quantity={item.quantity}
                      minimum={item.minimum_stock}
                      status={item.stock_status}
                      unit={item.base_unit_name_ar}
                    />
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            className="lg:col-span-2"
            title="آخر حركات المخزون"
            action={
              <Link href="/inventory" className="text-sm font-medium text-brand-700 hover:underline">
                المخزون
              </Link>
            }
          >
            {loading ? (
              <Rows />
            ) : !hasMovements ? (
              <Empty>لا توجد حركات بعد. أول حركة تكون عادة رصيداً افتتاحياً.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {data.movements?.items.map((movement) => {
                  const inbound = movement.direction === "in";
                  const Arrow = inbound ? ArrowDownLeft : ArrowUpRight;
                  return (
                    <li key={movement.id} className="flex items-center gap-3 px-5 py-3">
                      <Arrow
                        className={cn("size-4 shrink-0", inbound ? "text-brand-600" : "text-accent-600")}
                        aria-label={inbound ? "وارد" : "صادر"}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm text-ink">{movement.product_name_ar}</p>
                        <p className="truncate text-xs text-ink-muted">
                          {MOVEMENT_LABELS[movement.movement_type]}، {formatDateTime(movement.created_at)}
                        </p>
                      </div>
                      <span
                        className={cn(
                          "tabular shrink-0 text-sm font-semibold",
                          inbound ? "text-brand-700" : "text-accent-700",
                        )}
                        dir="ltr"
                      >
                        {inbound ? "+" : "−"}
                        {formatQuantity(movement.quantity)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Section>
        </div>
      ) : null}
    </div>
  );
}

function Figure({
  label,
  value,
  tone,
  note,
  loading,
  href,
  className,
}: {
  label: string;
  value: number | null;
  tone?: "warning" | "danger";
  note?: string;
  loading?: boolean;
  href?: string;
  className?: string;
}) {
  const highlighted = tone && value !== null && value > 0;
  const body = (
    <>
      <dt className="text-[13px] text-ink-muted">{label}</dt>
      <dd className="mt-1.5">
        {loading ? (
          <span className="block h-8 w-14 animate-pulse rounded bg-line" aria-hidden="true" />
        ) : (
          <span
            className={cn(
              "tabular block text-[28px] font-semibold leading-8",
              value === null ? "text-ink-muted/50" : "text-ink",
              highlighted && tone === "warning" && "text-accent-700",
              highlighted && tone === "danger" && "text-red-700",
            )}
          >
            {value === null ? "—" : formatQuantity(String(value))}
          </span>
        )}
        {note ? <span className="mt-1 block text-xs text-ink-muted">{note}</span> : null}
      </dd>
    </>
  );

  return href ? (
    <Link href={href} className={cn("block px-5 py-4 transition-colors hover:bg-brand-50/60", className)}>
      {body}
    </Link>
  ) : (
    <div className={cn("px-5 py-4", className)}>{body}</div>
  );
}

function Section({
  title,
  action,
  className,
  children,
}: {
  title: string;
  action?: ReactNode;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3.5">
        <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
        {action}
      </div>
      {children}
    </Card>
  );
}

function GettingStarted({ hasProducts, hasMovements }: { hasProducts: boolean; hasMovements: boolean }) {
  const steps = [
    {
      title: "أضف منتجاتك",
      body: "الاسم، رمز المنتج، وحدة البيع، السعر، والحد الأدنى الذي تريد التنبيه عنده.",
      href: "/products?new=1",
      cta: "إضافة منتج",
      done: hasProducts,
    },
    {
      title: "سجّل الرصيد الحالي",
      body: "أدخل الكمية الموجودة في المخزن لكل منتج كرصيد افتتاحي، كما في آخر نسخة من ملف الإكسل.",
      href: "/inventory",
      cta: "فتح المخزون",
      done: hasMovements,
    },
    {
      title: "تابع النواقص من هنا",
      body: "بعدها تظهر في هذه الصفحة المنتجات التي تحتاج إعادة طلب، وآخر ما دخل وخرج من المخزن.",
      done: false,
    },
  ];
  const current = steps.findIndex((step) => !step.done);

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-line px-5 py-4">
        <h2 className="text-[17px] font-semibold text-ink">ابدأ بتجهيز متجرك</h2>
        <p className="mt-1 text-sm text-ink-muted">ثلاث خطوات تنقل بياناتك من الإكسل إلى هنا.</p>
      </div>
      <ol className="divide-y divide-line">
        {steps.map((step, index) => (
          <li key={step.title} className={cn("flex flex-wrap gap-4 px-5 py-4", step.done && "opacity-60")}>
            <span
              className={cn(
                "tabular grid size-7 shrink-0 place-items-center rounded-full text-sm font-semibold",
                step.done
                  ? "bg-brand-700 text-white"
                  : index === current
                    ? "border-2 border-brand-700 text-brand-800"
                    : "border border-line-strong text-ink-muted",
              )}
              aria-hidden="true"
            >
              {step.done ? <Check className="size-4" /> : index + 1}
            </span>
            <div className="min-w-0 flex-1 basis-60">
              <p className="text-sm font-semibold text-ink">
                {step.title}
                {step.done ? <span className="sr-only"> (تم)</span> : null}
              </p>
              <p className="mt-0.5 max-w-prose text-sm leading-relaxed text-ink-muted">{step.body}</p>
            </div>
            {step.href && !step.done ? (
              <Link
                href={step.href}
                className={buttonClass(index === current ? "primary" : "secondary", "sm", "self-center")}
              >
                {step.cta}
              </Link>
            ) : null}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function Rows() {
  return (
    <div className="space-y-px" aria-busy="true">
      {["a", "b", "c", "d"].map((key) => (
        <div key={key} className="h-14 animate-pulse bg-surface/70" />
      ))}
      <span className="sr-only">جارٍ التحميل…</span>
    </div>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="px-5 py-10 text-center text-sm leading-relaxed text-ink-muted">{children}</p>;
}
