"use client";

import { ReceiptText } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { buttonClass } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { EmptyState, LoadError, Pagination, SearchBox, SkeletonRows } from "@/components/ui/data";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatDateTime, formatMoney, toNumber } from "@/lib/catalog";
import { type SaleList, listSales } from "@/lib/sales";

export default function SalesHistoryPage() {
  const { session } = useAuth();
  const seesAll = session?.permissions.includes("sales.discount") ?? false;

  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<SaleList | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listSales({ q: applied || undefined, page })
      .then((list) => {
        if (cancelled) return;
        setFailed(null);
        setResult(list);
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setFailed(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل الفواتير.");
      });
    return () => {
      cancelled = true;
    };
  }, [applied, page, attempt]);

  const totalPages = result ? Math.max(1, Math.ceil(result.total / result.page_size)) : 1;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-5 py-8 sm:px-8">
      <PageHeader
        title="الفواتير"
        description={seesAll ? "كل فواتير البيع في المتجر، الأحدث أولًا." : "الفواتير التي سجّلتها أنت، الأحدث أولًا."}
        actions={
          <Link href="/sales" className={buttonClass("primary")}>
            فاتورة جديدة
          </Link>
        }
      />

      <SearchBox
        value={query}
        onChange={setQuery}
        onSubmit={() => {
          setPage(1);
          setApplied(query.trim());
        }}
        label="ابحث في الفواتير"
        placeholder="رقم الفاتورة أو اسم العميل"
      />

      {failed ? <LoadError message={failed} onRetry={() => setAttempt((n) => n + 1)} /> : null}

      <Card className="overflow-hidden">
        {result === null && !failed ? (
          <SkeletonRows rows={5} />
        ) : result && result.items.length === 0 ? (
          <EmptyState
            icon={ReceiptText}
            title={applied ? "لا توجد فواتير تطابق البحث" : "لا توجد فواتير بعد"}
            body={applied ? "جرّب رقمًا آخر أو جزءًا من اسم العميل." : "كل فاتورة تحفظها من شاشة البيع تظهر هنا."}
          />
        ) : (
          <>
            <ul className="divide-y divide-line">
              {result?.items.map((sale) => (
                <li key={sale.id}>
                  <Link
                    href={`/sales/${sale.id}`}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-brand-50 sm:px-5"
                  >
                    <span className="w-16 text-sm font-bold tabular-nums text-ink">#{sale.number}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">
                        {sale.customer_name ?? "زبون نقدي"}
                      </span>
                      <span className="block text-xs text-ink-muted">
                        {formatDateTime(sale.created_at)}
                        {seesAll && sale.created_by_name ? `، ${sale.created_by_name}` : ""}
                      </span>
                    </span>
                    <span className="text-end text-sm">
                      <span className="block font-semibold tabular-nums text-ink">{formatMoney(sale.total)}</span>
                      {toNumber(sale.credit) > 0 ? (
                        <span className="block text-xs text-red-700">آجل {formatMoney(sale.credit)}</span>
                      ) : null}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <Pagination
              page={page}
              totalPages={totalPages}
              total={result?.total}
              noun="فاتورة"
              onChange={setPage}
            />
          </>
        )}
      </Card>
    </div>
  );
}
