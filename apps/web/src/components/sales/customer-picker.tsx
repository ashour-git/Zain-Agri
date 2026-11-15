"use client";

import { UserPlus, UserRound, X } from "lucide-react";
import { useEffect, useState } from "react";

import { buttonClass } from "@/components/ui/button";
import { Field, FormError, controlClass } from "@/components/ui/field";
import { FieldLabel } from "@/components/ui/info-tip";
import { ApiRequestError } from "@/lib/api";
import { formatMoney, toNumber } from "@/lib/catalog";
import { type Customer, createCustomer, listCustomers } from "@/lib/customers";
import { cn } from "@/lib/utils";

/** What the customer owes (or is owed), in words a shop owner uses. */
export function BalanceText({ balance }: { balance: string }) {
  const value = toNumber(balance);
  if (value > 0) return <span className="text-red-700">عليه {formatMoney(balance)}</span>;
  if (value < 0) return <span className="text-brand-700">له {formatMoney(String(-value))}</span>;
  return <span className="text-ink-muted">لا شيء عليه</span>;
}

/**
 * «زبون نقدي» by default. Choosing a customer allows paying part now and
 * leaving the rest on their account (آجل).
 */
export function CustomerPicker({
  customer,
  onChange,
}: {
  customer: Customer | null;
  onChange: (customer: Customer | null) => void;
}) {
  const [mode, setMode] = useState<"idle" | "search" | "new">("idle");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Customer[]>([]);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (mode !== "search") return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      listCustomers({ q: query.trim() || undefined, pageSize: 8 })
        .then((list) => !cancelled && setResults(list.items))
        .catch(() => undefined);
    }, 200);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mode, query]);

  const choose = (picked: Customer | null) => {
    onChange(picked);
    setMode("idle");
    setQuery("");
    setError(null);
  };

  const onCreate = async () => {
    if (!name.trim()) {
      setError("اكتب اسم العميل.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const created = await createCustomer({ name: name.trim(), phone: phone.trim() || undefined });
      setName("");
      setPhone("");
      choose(created);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر إضافة العميل.");
    } finally {
      setSaving(false);
    }
  };

  if (customer && mode === "idle") {
    return (
      <div className="flex items-center gap-3 rounded-md border border-brand-200 bg-brand-50 px-3 py-2.5">
        <UserRound className="size-5 shrink-0 text-brand-700" aria-hidden="true" />
        <div className="min-w-0 flex-1 text-sm">
          <p className="truncate font-semibold text-ink">{customer.name}</p>
          <p className="text-xs">
            <BalanceText balance={customer.balance} />
          </p>
        </div>
        <button
          type="button"
          onClick={() => choose(null)}
          className={buttonClass("ghost", "sm")}
          aria-label="إلغاء اختيار العميل والرجوع إلى زبون نقدي"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          onClick={() => choose(null)}
          className={cn(buttonClass(mode === "idle" ? "primary" : "secondary", "sm"))}
          aria-pressed={mode === "idle"}
        >
          زبون نقدي
        </button>
        <button
          type="button"
          onClick={() => setMode("search")}
          className={buttonClass(mode === "search" ? "primary" : "secondary", "sm")}
          aria-pressed={mode === "search"}
        >
          <UserRound className="size-4" aria-hidden="true" />
          عميل مسجّل
        </button>
        <button
          type="button"
          onClick={() => setMode("new")}
          className={buttonClass(mode === "new" ? "primary" : "secondary", "sm")}
          aria-pressed={mode === "new"}
        >
          <UserPlus className="size-4" aria-hidden="true" />
          عميل جديد
        </button>
      </div>

      {mode === "search" ? (
        <div className="space-y-1.5">
          <input
            type="search"
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="ابحث بالاسم أو رقم الموبايل"
            aria-label="ابحث عن عميل"
            className={controlClass}
          />
          <ul className="max-h-56 divide-y divide-line overflow-y-auto rounded-md border border-line">
            {results.length === 0 ? (
              <li className="px-3 py-3 text-sm text-ink-muted">لا يوجد عملاء بهذا الاسم. أضفه من «عميل جديد».</li>
            ) : (
              results.map((row) => (
                <li key={row.id}>
                  <button
                    type="button"
                    onClick={() => choose(row)}
                    className="flex w-full items-center gap-3 px-3 py-2 text-start text-sm hover:bg-brand-50"
                  >
                    <span className="min-w-0 flex-1 truncate font-medium text-ink">{row.name}</span>
                    <span className="text-xs">
                      <BalanceText balance={row.balance} />
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </div>
      ) : null}

      {mode === "new" ? (
        <div className="space-y-3 rounded-md border border-line p-3">
          <Field
            label="اسم العميل *"
            name="new-customer-name"
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            maxLength={120}
            placeholder="الحاج محمود"
          />
          <div className="space-y-1.5">
            <FieldLabel
              htmlFor="new-customer-phone"
              label="رقم الموبايل (اختياري)"
              info="لإرسال الفاتورة له على واتساب بضغطة واحدة. اكتبه كما هو، مثل 01012345678."
            />
            <input
              id="new-customer-phone"
              type="tel"
              inputMode="tel"
              dir="ltr"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
              placeholder="01012345678"
              className={cn(controlClass, "text-start")}
            />
          </div>
          <FormError>{error}</FormError>
          <button type="button" onClick={() => void onCreate()} disabled={saving} className={buttonClass("primary", "sm")}>
            {saving ? "جارٍ الإضافة…" : "إضافة واختيار"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
