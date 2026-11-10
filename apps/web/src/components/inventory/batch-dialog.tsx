"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Field, FormError } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError, apiRequest } from "@/lib/api";
import type { Batch } from "@/lib/types";

export function BatchDialog({
  productId,
  productName,
  onClose,
  onCreated,
}: {
  productId: string | null;
  productName: string | null;
  onClose: () => void;
  onCreated: (message: string) => void;
}) {
  const [batchNumber, setBatchNumber] = useState("");
  const [expiryDate, setExpiryDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async () => {
    setError(null);
    if (!productId) {
      setError("اختر منتجاً أولاً.");
      return;
    }
    if (!batchNumber.trim()) {
      setError("رقم الدفعة مطلوب.");
      return;
    }

    setPending(true);
    try {
      await apiRequest<Batch>("/api/v1/inventory/batches", {
        method: "POST",
        body: {
          product_id: productId,
          batch_number: batchNumber.trim(),
          expiry_date: expiryDate || null,
        },
      });
      onCreated(`تم إضافة الدفعة ${batchNumber.trim()}.`);
      onClose();
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError ? caught.message : "تعذّر حفظ الدفعة. حاول مرة أخرى.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="دفعة جديدة"
      description={
        productName
          ? `تُربط الدفعة بالمنتج ${productName}، وتبدأ برصيد صفر حتى تُسجَّل لها حركة.`
          : "تُربط الدفعة بالمنتج المحدد، وتبدأ برصيد صفر حتى تُسجَّل لها حركة."
      }
    >
      <div className="space-y-4">
        <FormError>{error}</FormError>

        <Field
          label="رقم الدفعة *"
          name="batch_number"
          dir="ltr"
          value={batchNumber}
          onChange={(event) => setBatchNumber(event.target.value)}
          placeholder="B-2026-01"
        />
        <Field
          label="تاريخ الصلاحية"
          name="batch_expiry"
          type="date"
          dir="ltr"
          value={expiryDate}
          onChange={(event) => setExpiryDate(event.target.value)}
          hint="تاريخ اختياري. لا يوجد بعد أي إجراء تلقائي للمنتجات قاربة الانتهاء."
        />

        <div className="flex items-center justify-end gap-2 border-t border-line pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-line px-4 py-2 text-xs text-ink-muted transition-colors hover:text-ink"
          >
            إلغاء
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={pending}
            className="inline-flex items-center gap-2 rounded-md bg-brand-700 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
            إضافة الدفعة
          </button>
        </div>
      </div>
    </Modal>
  );
}
