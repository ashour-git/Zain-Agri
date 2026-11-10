"use client";

import { ChevronDown, History, RefreshCw, ShieldOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, LoadError, Pagination, SkeletonRows, selectClass } from "@/components/ui/data";
import { ApiRequestError, FIELD_LABELS, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { MOVEMENT_LABELS, formatDateTime } from "@/lib/catalog";
import type { AuditList, AuditLog } from "@/lib/types";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

const ENTITY_LABELS: Record<string, string> = {
  product: "المنتجات",
  stock_movement: "حركات المخزون",
  product_batch: "الدفعات",
  product_category: "التصنيفات",
  brand: "العلامات التجارية",
  product_unit_conversion: "تحويلات الوحدات",
  assistant: "أسئلة المساعد",
};

const ACTION_LABELS: Record<string, string> = {
  "product.created": "إضافة منتج",
  "product.updated": "تعديل منتج",
  "product.archived": "أرشفة منتج",
  "product.restored": "استعادة منتج",
  "category.created": "إضافة تصنيف",
  "category.updated": "تعديل تصنيف",
  "brand.created": "إضافة علامة تجارية",
  "conversion.created": "إضافة تحويل وحدات",
  "inventory.movement.created": "حركة مخزون",
  "batch.created": "إضافة دفعة",
  "assistant.asked": "سؤال للمساعد",
};

const ACTION_VARIANTS: Record<string, "brand" | "warning" | "neutral"> = {
  created: "brand",
  updated: "warning",
  archived: "neutral",
  restored: "brand",
  asked: "neutral",
};

function actionVariant(action: string) {
  return ACTION_VARIANTS[action.split(".").at(-1) ?? ""] ?? "neutral";
}

const VALUE_LABELS: Record<string, string> = {
  active: "نشط",
  archived: "مؤرشف",
  in: "وارد",
  out: "صادر",
  ...MOVEMENT_LABELS,
};

function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "نعم" : "لا";
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  return VALUE_LABELS[text] ?? text;
}

/** Internal references (UUIDs) mean nothing to a shop owner; the name is shown in the row title. */
const isInternal = (key: string) => key === "id" || key.endsWith("_id") || key.endsWith("_by");

/** Fields whose value differs between the before and after snapshots, in readable form. */
function changes(log: AuditLog): { key: string; label: string; before: string; after: string }[] {
  const before = log.before_state ?? {};
  const after = log.after_state ?? {};
  const keys = Array.from(new Set([...Object.keys(before), ...Object.keys(after)]));
  return (
    keys
      .filter((key) => !isInternal(key))
      .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
      .map((key) => ({
        key,
        label: FIELD_LABELS[key] ?? key,
        before: display(before[key]),
        after: display(after[key]),
      }))
      // A creation has no "before"; listing empty optional fields is noise.
      .filter((row) => log.before_state !== null || row.after !== "—")
  );
}

function subject(log: AuditLog): string | null {
  const state = log.after_state ?? log.before_state ?? {};
  const name = state.name_ar ?? state.name ?? state.product_name_ar ?? state.batch_number ?? state.sku;
  return typeof name === "string" ? name : null;
}

export default function AuditPage() {
  const { session } = useAuth();
  const allowed = (session?.permissions ?? []).includes("audit.read");
  const tenantId = session?.tenant?.id ?? "";

  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [result, setResult] = useState<{ key: string; data: AuditList } | null>(null);
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null);
  const refresh = () => setRefreshKey((current) => current + 1);

  const params = useMemo(() => {
    const next = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    if (entityType) next.set("entity_type", entityType);
    return next.toString();
  }, [page, entityType]);

  const requestKey = `${tenantId}|${params}|${refreshKey}`;
  const loading = allowed && result?.key !== requestKey && failure?.key !== requestKey;
  const failed = failure?.key === requestKey ? failure.message : null;
  const data = result?.data ?? null;
  const items = data?.items ?? [];
  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    void apiRequest<AuditList>(`/api/v1/audit?${params}`)
      .then((rows) => {
        if (!cancelled) setResult({ key: requestKey, data: rows });
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setFailure({
          key: requestKey,
          message: caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل سجل التعديلات.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [allowed, params, requestKey]);

  if (!allowed) {
    return (
      <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
        <Card>
          <EmptyState
            icon={ShieldOff}
            title="هذه الصفحة لمالك المتجر والمدير"
            body="اطلب من مالك المتجر منحك صلاحية «عرض سجل التدقيق» إذا كنت تحتاجها."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-4 px-4 py-6 sm:px-8 sm:py-8">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="entity-filter" className="text-sm text-ink-muted">
          عرض
        </label>
        <select
          id="entity-filter"
          value={entityType}
          onChange={(event) => {
            setPage(1);
            setExpanded(null);
            setEntityType(event.target.value);
          }}
          className={selectClass}
        >
          <option value="">كل التعديلات</option>
          {Object.entries(ENTITY_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <button type="button" onClick={refresh} disabled={loading} className={buttonClass("ghost", "md", "ms-auto")}>
          <RefreshCw className={cn("size-4", loading && "animate-spin")} aria-hidden="true" />
          تحديث
        </button>
      </div>

      {failed ? <LoadError message={failed} onRetry={refresh} /> : null}

      <Card className="overflow-hidden">
        {loading && items.length === 0 ? (
          <SkeletonRows />
        ) : items.length === 0 && !failed ? (
          <EmptyState
            icon={History}
            title="لا توجد تعديلات بعد"
            body="كل إضافة أو تعديل على المنتجات والمخزون يُسجَّل هنا تلقائياً، مع اسم من قام به ووقته."
          />
        ) : (
          <ul className={cn("divide-y divide-line", loading && "opacity-60")}>
            {items.map((log) => {
              const open = expanded === log.id;
              const diff = open ? changes(log) : [];
              const name = subject(log);
              return (
                <li key={log.id}>
                  <button
                    type="button"
                    onClick={() => setExpanded(open ? null : log.id)}
                    aria-expanded={open}
                    className="grid min-h-14 w-full grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-4 py-3 text-start transition-colors hover:bg-brand-50/40 sm:grid-cols-[9rem_1fr_12rem_auto] sm:px-5"
                  >
                    <span className="sm:order-none">
                      <Badge variant={actionVariant(log.action)}>{ACTION_LABELS[log.action] ?? log.action}</Badge>
                    </span>
                    <ChevronDown
                      className={cn(
                        "size-4 shrink-0 text-ink-muted transition-transform sm:order-last",
                        open && "rotate-180",
                      )}
                      aria-hidden="true"
                    />
                    <span className="col-span-2 min-w-0 truncate text-sm font-medium text-ink sm:col-span-1">
                      {name ?? ENTITY_LABELS[log.entity_type] ?? log.entity_type}
                    </span>
                    <span className="col-span-2 truncate text-[13px] text-ink-muted sm:col-span-1">
                      {log.actor_name ?? "النظام"}، {formatDateTime(log.created_at)}
                    </span>
                  </button>
                  {open ? (
                    <div className="border-t border-line bg-surface/60 px-4 py-3 sm:px-5">
                      {diff.length === 0 ? (
                        <p className="text-sm text-ink-muted">لا توجد تفاصيل محفوظة لهذا التعديل.</p>
                      ) : (
                        <div className="overflow-x-auto">
                          <table className="w-full max-w-2xl text-sm">
                            <thead className="text-[13px] text-ink-muted">
                              <tr>
                                <th className="w-2/5 py-2 pe-4 text-start font-medium">الحقل</th>
                                {log.before_state ? (
                                  <>
                                    <th className="py-2 pe-4 text-start font-medium">كان</th>
                                    <th className="py-2 text-start font-medium">أصبح</th>
                                  </>
                                ) : (
                                  <th className="py-2 text-start font-medium">القيمة</th>
                                )}
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-line">
                              {diff.map((row) => (
                                <tr key={row.key}>
                                  <td className="py-2 pe-4 text-ink-muted">{row.label}</td>
                                  {log.before_state ? (
                                    <td className="break-words py-2 pe-4 text-ink-muted line-through decoration-red-400">
                                      {row.before}
                                    </td>
                                  ) : null}
                                  <td className="break-words py-2 font-medium text-ink">{row.after}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}

        {data && data.total > 0 ? (
          <Pagination
            page={data.page}
            totalPages={totalPages}
            total={data.total}
            noun="تعديل"
            disabled={loading}
            onChange={(next) => {
              setExpanded(null);
              setPage(next);
            }}
          />
        ) : null}
      </Card>
    </div>
  );
}
