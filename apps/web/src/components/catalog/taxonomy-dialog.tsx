"use client";

import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Field, FormError, SelectField } from "@/components/ui/field";
import { Modal } from "@/components/ui/modal";
import { ApiRequestError, apiRequest } from "@/lib/api";
import type { Brand, Category } from "@/lib/types";

export function TaxonomyDialog({
  categories,
  onClose,
  onCreated,
}: {
  categories: Category[];
  onClose: () => void;
  onCreated: (message: string) => void;
}) {
  const [mode, setMode] = useState<"category" | "brand">("category");
  const [name, setName] = useState("");
  const [nameAr, setNameAr] = useState("");
  const [parentId, setParentId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const reset = () => {
    setName("");
    setNameAr("");
    setParentId("");
    setError(null);
  };

  const submit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("الاسم مطلوب.");
      return;
    }
    setPending(true);
    try {
      if (mode === "category") {
        await apiRequest<Category>("/api/v1/categories", {
          method: "POST",
          body: {
            name: name.trim(),
            name_ar: nameAr.trim() || null,
            parent_id: parentId || null,
          },
        });
        onCreated("تم إضافة التصنيف.");
      } else {
        await apiRequest<Brand>("/api/v1/brands", {
          method: "POST",
          body: { name: name.trim(), name_ar: nameAr.trim() || null },
        });
        onCreated("تم إضافة العلامة التجارية.");
      }
      reset();
      onClose();
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError ? caught.message : "تعذّر الحفظ. حاول مرة أخرى.",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="التصنيفات والعلامات"
      description="التصنيف والعلامة يظهران في بحث المنتجات وتقارير المخزون."
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2 rounded-xl bg-surface p-1">
          {(
            [
              { id: "category", label: "تصنيف" },
              { id: "brand", label: "علامة تجارية" },
            ] as const
          ).map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => {
                setMode(tab.id);
                reset();
              }}
              className={`rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
                mode === tab.id ? "bg-white text-brand-800 shadow-sm" : "text-ink-muted"
              }`}
              aria-pressed={mode === tab.id}
            >
              {tab.label}
            </button>
          ))}
        </div>

        <FormError>{error}</FormError>

        <Field
          label="الاسم *"
          name="taxonomy_name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={mode === "category" ? "بذور" : "شل"}
        />
        <Field
          label="الاسم بالعربية"
          name="taxonomy_name_ar"
          value={nameAr}
          onChange={(event) => setNameAr(event.target.value)}
          placeholder={mode === "category" ? "بذور" : "شل"}
        />
        {mode === "category" ? (
          <SelectField
            label="التصنيف الأب"
            name="taxonomy_parent"
            value={parentId}
            onChange={(event) => setParentId(event.target.value)}
          >
            <option value="">تصنيف رئيسي</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name_ar ?? category.name}
              </option>
            ))}
          </SelectField>
        ) : null}

        <div className="flex items-center justify-end gap-2 border-t border-line pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-line px-4 py-2 text-xs text-ink-muted transition-colors hover:text-ink"
          >
            إغلاق
          </button>
          <button
            type="button"
            onClick={() => void submit()}
            disabled={pending}
            className="inline-flex items-center gap-2 rounded-xl bg-brand-700 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden="true" /> : null}
            إضافة
          </button>
        </div>
      </div>
    </Modal>
  );
}
