"use client";

import { UserPlus, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BalanceText } from "@/components/sales/customer-picker";
import { buttonClass } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { EmptyState, LoadError, Pagination, SearchBox, Segmented, SkeletonRows } from "@/components/ui/data";
import { Field, FormError } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { type CustomerList, createCustomer, listCustomers } from "@/lib/customers";

type Filter = "all" | "owes";

function AddCustomerDialog({
  open,
  canAdjust,
  onClose,
  onCreated,
}: {
  open: boolean;
  canAdjust: boolean;
  onClose: () => void;
  onCreated: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [opening, setOpening] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSave = async () => {
    if (!name.trim()) {
      setError("اكتب اسم العميل.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createCustomer({
        name: name.trim(),
        phone: phone.trim() || undefined,
        opening_balance: canAdjust && opening.trim() ? opening.trim() : undefined,
      });
      onCreated(created.id);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر إضافة العميل.");
      setSaving(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="عميل جديد" description="العميل المسجّل يقدر يشتري بالآجل، ويظهر حسابه هنا.">
      <div className="space-y-4 px-5 py-4">
        <Field
          label="اسم العميل *"
          name="customer-name"
          autoFocus
          value={name}
          onChange={(event) => setName(event.target.value)}
          maxLength={120}
          placeholder="الحاج محمود"
        />
        <Field
          label="رقم الموبايل (اختياري)"
          info="لإرسال الفواتير له على واتساب بضغطة واحدة. اكتبه كما هو، مثل 01012345678."
          name="customer-phone"
          type="tel"
          inputMode="tel"
          dir="ltr"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          placeholder="01012345678"
        />
        {canAdjust ? (
          <Field
            label="رصيد سابق عليه (اختياري)"
            info="لو العميل عليه فلوس من قبل استخدام البرنامج (من الدفتر مثلًا)، اكتب المبلغ هنا. لو المحل هو اللي عليه فلوس للعميل اكتبه بالسالب، مثل -200."
            name="customer-opening"
            inputMode="decimal"
            value={opening}
            onChange={(event) => setOpening(event.target.value)}
            placeholder="0"
          />
        ) : null}
        <FormError>{error}</FormError>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={buttonClass("ghost")}>
            إلغاء
          </button>
          <button type="button" onClick={() => void onSave()} disabled={saving} className={buttonClass("primary")}>
            {saving ? "جارٍ الحفظ…" : "إضافة العميل"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function CustomersPage() {
  const { session } = useAuth();
  const router = useRouter();
  const permissions = session?.permissions ?? [];
  const canSell = permissions.includes("sales.operate");
  const canAdjust = permissions.includes("customers.adjust");

  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<CustomerList | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (!canSell) return;
    let cancelled = false;
    listCustomers({ q: applied || undefined, owes: filter === "owes", page, pageSize: 25 })
      .then((list) => {
        if (cancelled) return;
        setFailed(null);
        setResult(list);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setFailed(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل العملاء.");
      });
    return () => {
      cancelled = true;
    };
  }, [canSell, applied, filter, page, attempt]);

  if (!canSell) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <FormError>ليست لديك صلاحية العملاء. اطلبها من مالك المتجر.</FormError>
      </div>
    );
  }

  const totalPages = result ? Math.max(1, Math.ceil(result.total / result.page_size)) : 1;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-5 py-8 sm:px-8">
      <PageHeader
        title="العملاء"
        description="من يشتري بالآجل، وكم عليه، وكل حركة في حسابه."
        actions={
          <button type="button" onClick={() => setAdding(true)} className={buttonClass("primary")}>
            <UserPlus className="size-4" aria-hidden="true" />
            عميل جديد
          </button>
        }
      />

      <div className="flex flex-wrap items-center gap-3">
        <SearchBox
          value={query}
          onChange={setQuery}
          onSubmit={() => {
            setPage(1);
            setApplied(query.trim());
          }}
          label="ابحث عن عميل"
          placeholder="الاسم أو رقم الموبايل"
        />
        <Segmented
          label="عرض"
          value={filter}
          options={[
            { id: "all", label: "الكل" },
            { id: "owes", label: "عليهم فلوس" },
          ]}
          onChange={(value) => {
            setPage(1);
            setFilter(value);
          }}
        />
      </div>

      {failed ? <LoadError message={failed} onRetry={() => setAttempt((n) => n + 1)} /> : null}

      <Card className="overflow-hidden">
        {result === null && !failed ? (
          <SkeletonRows rows={5} />
        ) : result && result.items.length === 0 ? (
          <EmptyState
            icon={Users}
            title={filter === "owes" ? "لا أحد عليه فلوس الآن" : applied ? "لا يوجد عميل بهذا البحث" : "لا يوجد عملاء بعد"}
            body={
              filter === "owes"
                ? "كل العملاء حساباتهم صفر أو لهم فلوس عند المحل."
                : "أضف عميلًا من الزر أعلى الصفحة، أو من شاشة البيع عند أول فاتورة آجل له."
            }
          />
        ) : (
          <>
            <ul className="divide-y divide-line">
              {result?.items.map((customer) => (
                <li key={customer.id}>
                  <Link
                    href={`/customers/${customer.id}`}
                    className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-brand-50 sm:px-5"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-ink">
                        {customer.name}
                        {customer.active ? null : <span className="ms-2 text-xs text-ink-muted">(موقوف)</span>}
                      </span>
                      {customer.phone ? (
                        <span className="block text-xs text-ink-muted" dir="ltr">
                          {customer.phone}
                        </span>
                      ) : null}
                    </span>
                    <span className="text-sm font-semibold tabular-nums">
                      <BalanceText balance={customer.balance} />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <Pagination page={page} totalPages={totalPages} total={result?.total} noun="عميل" onChange={setPage} />
          </>
        )}
      </Card>

      {adding ? (
        <AddCustomerDialog
          open={adding}
          canAdjust={canAdjust}
          onClose={() => setAdding(false)}
          onCreated={(id) => router.push(`/customers/${id}`)}
        />
      ) : null}
    </div>
  );
}
