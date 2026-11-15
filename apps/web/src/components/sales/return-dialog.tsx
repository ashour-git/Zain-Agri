"use client";

import { useState } from "react";

import { buttonClass } from "@/components/ui/button";
import { FormError, TextareaField, controlClass } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError } from "@/lib/api";
import { formatMoney, formatQuantity, toNumber } from "@/lib/catalog";
import { type ReturnResult, type Sale, createReturn } from "@/lib/sales";
import { cn } from "@/lib/utils";

/** «مرتجع»: choose quantities per line; money comes off the debt first, the rest is cash. */
export function ReturnDialog({
  sale,
  open,
  onClose,
  onDone,
}: {
  sale: Sale;
  open: boolean;
  onClose: () => void;
  onDone: (result: ReturnResult) => void;
}) {
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const left = (line: Sale["lines"][number]) => toNumber(line.quantity) - toNumber(line.returned_quantity);
  const chosen = sale.lines
    .map((line) => ({ line, quantity: toNumber(quantities[line.id]) }))
    .filter((entry) => entry.quantity > 0);
  const tooMany = chosen.find((entry) => entry.quantity > left(entry.line));

  const onSubmit = async () => {
    if (chosen.length === 0) {
      setError("اكتب كمية المرتجع لصنف واحد على الأقل.");
      return;
    }
    if (tooMany) {
      setError(`لا يمكن إرجاع أكثر من ${formatQuantity(String(left(tooMany.line)))} من «${tooMany.line.name_ar}».`);
      return;
    }
    if (reason.trim().length < 3) {
      setError("اكتب سبب المرتجع (3 أحرف على الأقل).");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const result = await createReturn(sale.id, {
        reason: reason.trim(),
        lines: chosen.map((entry) => ({ line_id: entry.line.id, quantity: String(entry.quantity) })),
      });
      setQuantities({});
      setReason("");
      onDone(result);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : "تعذّر تسجيل المرتجع.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`مرتجع من فاتورة رقم ${sale.number}`}
      description="اكتب الكمية التي رجعت من كل صنف. ترجع للمخزون، وقيمتها تُخصم أولًا مما على العميل من هذه الفاتورة، والباقي يُرد له نقدًا."
    >
      <div className="space-y-4 px-5 py-4">
        <ul className="divide-y divide-line rounded-md border border-line">
          {sale.lines.map((line) => {
            const available = left(line);
            return (
              <li key={line.id} className="flex items-center gap-3 px-3 py-2.5">
                <div className="min-w-0 flex-1 text-sm">
                  <p className="truncate font-medium text-ink">{line.name_ar}</p>
                  <p className="text-xs text-ink-muted">
                    بيع {formatQuantity(line.quantity)} {line.unit_name_ar} بسعر {formatMoney(line.unit_price)}
                    {toNumber(line.returned_quantity) > 0 ? `، رجع منه ${formatQuantity(line.returned_quantity)}` : ""}
                  </p>
                </div>
                {available > 0 ? (
                  <input
                    inputMode="decimal"
                    aria-label={`كمية المرتجع من ${line.name_ar} (حتى ${formatQuantity(String(available))})`}
                    placeholder={`حتى ${formatQuantity(String(available))}`}
                    value={quantities[line.id] ?? ""}
                    onChange={(event) => setQuantities((current) => ({ ...current, [line.id]: event.target.value }))}
                    className={cn(controlClass, "w-24 tabular-nums")}
                  />
                ) : (
                  <span className="text-xs text-ink-muted">رجع بالكامل</span>
                )}
              </li>
            );
          })}
        </ul>
        <TextareaField
          label="سبب المرتجع *"
          name="return-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={300}
          rows={2}
          placeholder="الزبون رجّع شيكارة مفتوحة"
        />
        <FormError>{error}</FormError>
        <div className="flex flex-wrap justify-end gap-2">
          <button type="button" onClick={onClose} className={buttonClass("ghost")}>
            إلغاء
          </button>
          <button type="button" onClick={() => void onSubmit()} disabled={saving} className={buttonClass("primary")}>
            {saving ? "جارٍ التسجيل…" : "تسجيل المرتجع"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
