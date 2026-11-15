"use client";

import { HandCoins, PencilLine, ReceiptText } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { BalanceText } from "@/components/sales/customer-picker";
import { buttonClass } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { EmptyState, LoadError, SkeletonRows } from "@/components/ui/data";
import { Field, FormError, FormNotice, TextareaField } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatDateTime, formatMoney, toNumber } from "@/lib/catalog";
import { KIND_LABELS, type Statement, getStatement, recordCorrection, recordPayment } from "@/lib/customers";
import { cn } from "@/lib/utils";

type Dialog = "payment" | "correction" | null;

function MoneyDialog({
  kind,
  customerName,
  onClose,
  onSave,
}: {
  kind: Exclude<Dialog, null>;
  customerName: string;
  onClose: () => void;
  onSave: (amount: string, text: string) => Promise<void>;
}) {
  const [amount, setAmount] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const payment = kind === "payment";

  const submit = async () => {
    const value = toNumber(amount);
    if (payment ? value <= 0 : value === 0) {
      setError(payment ? "اكتب المبلغ الذي دفعه العميل." : "اكتب مبلغ التصحيح (موجب أو سالب).");
      return;
    }
    if (!payment && text.trim().length < 3) {
      setError("اكتب سبب التصحيح (3 أحرف على الأقل).");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onSave(amount.trim(), text.trim());
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر الحفظ.");
      setSaving(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={payment ? `تحصيل من ${customerName}` : `تصحيح حساب ${customerName}`}
      description={
        payment
          ? "مبلغ دفعه العميل من حسابه. يُخصم مما عليه، ولو دفع أكثر يصبح له رصيد عند المحل."
          : "لتصليح خطأ في الحساب فقط. لا يُمسح شيء: يُضاف سطر جديد بالسبب ويظهر في الكشف."
      }
    >
      <div className="space-y-4 px-5 py-4">
        <Field
          label={payment ? "المبلغ المدفوع *" : "مبلغ التصحيح *"}
          info={
            payment
              ? undefined
              : "موجب يزيد ما على العميل (مثلًا نسيت تسجّل عليه 100 فاكتب 100). سالب يقلّله (مثلًا -100)."
          }
          name="money-amount"
          autoFocus
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
          placeholder={payment ? "500" : "-100"}
        />
        <TextareaField
          label={payment ? "ملاحظة (اختياري)" : "سبب التصحيح *"}
          name="money-text"
          value={text}
          onChange={(event) => setText(event.target.value)}
          maxLength={300}
          rows={2}
          placeholder={payment ? "دفع كاش" : "فاتورة قديمة اتسجلت مرتين"}
        />
        <FormError>{error}</FormError>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={buttonClass("ghost")}>
            إلغاء
          </button>
          <button type="button" onClick={() => void submit()} disabled={saving} className={buttonClass("primary")}>
            {saving ? "جارٍ الحفظ…" : payment ? "تسجيل التحصيل" : "تسجيل التصحيح"}
          </button>
        </div>
      </div>
    </Modal>
  );
}

export default function CustomerStatementPage() {
  const { id } = useParams<{ id: string }>();
  const { session } = useAuth();
  const canAdjust = session?.permissions.includes("customers.adjust") ?? false;

  const [statement, setStatement] = useState<Statement | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    getStatement(id)
      .then((result) => {
        setFailed(null);
        setStatement(result);
      })
      .catch((caught: unknown) =>
        setFailed(caught instanceof ApiRequestError ? caught.message : "تعذّر تحميل كشف الحساب."),
      );
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  if (failed) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <LoadError message={failed} onRetry={load} />
      </div>
    );
  }
  if (!statement) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <SkeletonRows rows={5} />
      </div>
    );
  }

  const { customer } = statement;

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-5 py-8 sm:px-8">
      <PageHeader
        title={customer.name}
        description={customer.phone ?? "بدون رقم موبايل"}
        actions={
          <Link href="/customers" className={buttonClass("ghost", "sm")}>
            كل العملاء
          </Link>
        }
      />

      <FormNotice>{notice}</FormNotice>

      <Card className="flex flex-wrap items-center gap-4 p-5">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-ink-muted">الرصيد الآن</p>
          <p className="whitespace-nowrap text-xl font-bold tabular-nums">
            <BalanceText balance={statement.balance} />
          </p>
        </div>
        <button type="button" onClick={() => setDialog("payment")} className={buttonClass("primary")}>
          <HandCoins className="size-4" aria-hidden="true" />
          تحصيل
        </button>
        {canAdjust ? (
          <button type="button" onClick={() => setDialog("correction")} className={buttonClass("secondary")}>
            <PencilLine className="size-4" aria-hidden="true" />
            تصحيح
          </button>
        ) : null}
      </Card>

      <Card className="overflow-hidden">
        <div className="border-b border-line px-5 py-3">
          <h2 className="text-[15px] font-semibold text-ink">كشف الحساب</h2>
          <p className="text-xs text-ink-muted">كل حركة بالترتيب من الأقدم، والرصيد بعد كل حركة.</p>
        </div>
        {statement.lines.length === 0 ? (
          <EmptyState
            icon={ReceiptText}
            title="لا توجد حركات بعد"
            body="أول فاتورة آجل أو تحصيل لهذا العميل يظهر هنا."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-ink-muted">
                  <th scope="col" className="px-4 py-2 text-start font-medium sm:px-5">الحركة</th>
                  <th scope="col" className="px-3 py-2 text-end font-medium">المبلغ</th>
                  <th scope="col" className="px-4 py-2 text-end font-medium sm:px-5">الرصيد بعدها</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {statement.lines.map((line) => {
                  const amount = toNumber(line.amount);
                  return (
                    <tr key={line.id}>
                      <td className="px-4 py-2.5 sm:px-5">
                        <span className="font-medium text-ink">{KIND_LABELS[line.kind]}</span>
                        <span className="block text-xs text-ink-muted">{formatDateTime(line.created_at)}</span>
                        {line.note && line.note !== KIND_LABELS[line.kind] ? (
                          <span className="block text-xs text-ink-muted">{line.note}</span>
                        ) : null}
                        {line.reference_type === "sales_invoice" && line.reference_id ? (
                          <Link href={`/sales/${line.reference_id}`} className="text-xs text-brand-700 underline">
                            فتح الفاتورة
                          </Link>
                        ) : null}
                      </td>
                      <td
                        className={cn(
                          "whitespace-nowrap px-3 py-2.5 text-end tabular-nums",
                          amount > 0 ? "text-red-700" : "text-brand-700",
                        )}
                      >
                        {amount > 0 ? "+" : "−"}
                        {formatMoney(String(Math.abs(amount)))}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-end text-xs tabular-nums sm:px-5">
                        <BalanceText balance={line.balance_after} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {dialog ? (
        <MoneyDialog
          kind={dialog}
          customerName={customer.name}
          onClose={() => setDialog(null)}
          onSave={async (amount, text) => {
            if (dialog === "payment") {
              await recordPayment(customer.id, { amount, note: text || undefined });
              setNotice(`سُجّل تحصيل ${formatMoney(amount)} من ${customer.name}.`);
            } else {
              await recordCorrection(customer.id, { amount, reason: text });
              setNotice("سُجّل التصحيح في كشف الحساب.");
            }
            setDialog(null);
            load();
          }}
        />
      ) : null}
    </div>
  );
}
