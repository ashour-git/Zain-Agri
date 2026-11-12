"use client";

import { Download, FileSpreadsheet, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, PageHeader } from "@/components/ui/card";
import { selectClass } from "@/components/ui/data";
import { FormError, FormNotice } from "@/components/ui/field";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import { formatQuantity } from "@/lib/catalog";
import {
  type Analysis,
  type CommitResult,
  FIELD_LABELS,
  FIELD_ORDER,
  type ImportField,
  type ImportOptions,
  type Preview,
  analyzeFile,
  commitImport,
  downloadTemplate,
  previewImport,
} from "@/lib/importer";
import { getUnits } from "@/lib/reference";
import type { UnitOfMeasure } from "@/lib/types";
import { cn } from "@/lib/utils";

type Step = "file" | "columns" | "preview" | "done";
type Mapping = Record<number, ImportField | "">;

const message = (caught: unknown, fallback: string) =>
  caught instanceof ApiRequestError ? caught.message : fallback;

const STEPS: { id: Step; label: string }[] = [
  { id: "file", label: "الملف" },
  { id: "columns", label: "الأعمدة" },
  { id: "preview", label: "المعاينة" },
  { id: "done", label: "النتيجة" },
];

function Steps({ current }: { current: Step }) {
  const at = STEPS.findIndex((step) => step.id === current);
  return (
    <ol className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm" aria-label="خطوات الاستيراد">
      {STEPS.map((step, index) => (
        <li
          key={step.id}
          aria-current={index === at ? "step" : undefined}
          className={cn(
            "flex items-center gap-2",
            index === at ? "font-semibold text-brand-800" : index < at ? "text-ink" : "text-ink-muted",
          )}
        >
          <span
            className={cn(
              "grid size-6 place-items-center rounded-full border text-xs tabular-nums",
              index === at
                ? "border-brand-700 bg-brand-700 text-white"
                : index < at
                  ? "border-brand-300 bg-brand-50 text-brand-800"
                  : "border-line-strong",
            )}
          >
            {index + 1}
          </span>
          {step.label}
        </li>
      ))}
    </ol>
  );
}

export default function ImportPage() {
  const { session } = useAuth();
  const allowed =
    (session?.permissions.includes("products.create") ?? false) &&
    (session?.permissions.includes("inventory.adjust") ?? false);

  const [step, setStep] = useState<Step>("file");
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [units, setUnits] = useState<UnitOfMeasure[]>([]);
  const [options, setOptions] = useState<ImportOptions>({
    default_unit_id: null,
    create_categories: true,
    create_brands: true,
    skip_errors: false,
  });
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<CommitResult | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getUnits()
      .then((list) => {
        setUnits(list);
        const piece = list.find((unit) => unit.code === "piece");
        if (piece) setOptions((current) => ({ ...current, default_unit_id: piece.id }));
      })
      .catch(() => setUnits([]));
  }, []);

  if (!allowed) {
    return (
      <div className="mx-auto w-full max-w-3xl px-5 py-8 sm:px-8">
        <FormError>الاستيراد يحتاج صلاحية إضافة المنتجات وتسجيل المخزون. اطلبها من مالك المتجر.</FormError>
      </div>
    );
  }

  const run = async (label: string, action: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(message(caught, "تعذّر إكمال الطلب. حاول مرة أخرى."));
    } finally {
      setBusy(null);
    }
  };

  const analyze = (chosen: File, sheet?: string) =>
    run("analyze", async () => {
      const result = await analyzeFile(chosen, sheet);
      setFile(chosen);
      setAnalysis(result);
      const next: Mapping = {};
      for (const column of result.columns) next[column.index] = column.field ?? "";
      setMapping(next);
      setPreview(null);
      setStep("columns");
    });

  const setField = (index: number, field: ImportField | "") => {
    setMapping((current) => {
      const next = { ...current, [index]: field };
      // A field belongs to one column: choosing it here frees it elsewhere.
      if (field) {
        for (const other of Object.keys(next)) {
          if (Number(other) !== index && next[Number(other)] === field) next[Number(other)] = "";
        }
      }
      return next;
    });
    setPreview(null);
  };

  const hasName = Object.values(mapping).includes("name_ar");

  const showPreview = () =>
    run("preview", async () => {
      if (!analysis) return;
      setPreview(await previewImport(analysis, mapping, options));
      setStep("preview");
    });

  const create = () =>
    run("commit", async () => {
      if (!analysis) return;
      setResult(await commitImport(analysis, mapping, options));
      setStep("done");
    });

  const problems = preview?.rows.filter((row) => row.status === "error") ?? [];
  const skipped = preview?.rows.filter((row) => row.status === "skip") ?? [];
  const creating = preview?.rows.filter((row) => row.status === "create") ?? [];
  const canCreate =
    preview !== null && preview.counts.create > 0 && (preview.counts.error === 0 || options.skip_errors);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-4 py-6 sm:px-8">
      <PageHeader
        title="استيراد المنتجات من ملف"
        description="ارفع ملف Excel أو csv بأي ترتيب للأعمدة، وراجع ما سيُضاف قبل الحفظ."
        actions={
          <Link href="/products" className={buttonClass("ghost", "sm")}>
            العودة إلى المنتجات
          </Link>
        }
      />
      <Steps current={step} />
      <FormError>{error}</FormError>

      {step === "file" ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileSpreadsheet className="size-4 text-brand-600" aria-hidden="true" />
              اختر الملف
            </CardTitle>
            <CardDescription>
              ملف بصيغة xlsx أو csv، حتى 4 ميجابايت و500 صف في المرة. إذا كان ملفك بصيغة xls القديمة،
              افتحه في Excel واحفظه بصيغة xlsx.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <label htmlFor="import-file" className="mb-1.5 block text-[13px] font-medium text-ink">
                الملف
              </label>
              <input
                id="import-file"
                type="file"
                accept=".xlsx,.csv"
                disabled={busy !== null}
                onChange={(event) => {
                  const chosen = event.target.files?.[0];
                  if (chosen) void analyze(chosen);
                }}
                className={cn(selectClass, "w-full cursor-pointer py-2")}
              />
              {busy === "analyze" ? (
                <p className="mt-2 flex items-center gap-2 text-sm text-ink-muted" role="status">
                  <Loader2 className="size-4 animate-spin" aria-hidden="true" />
                  جارٍ قراءة الملف…
                </p>
              ) : null}
            </div>
            <p className="rounded-md border border-line bg-panel px-3 py-2.5 text-[13px] leading-relaxed text-ink-muted">
              للتعرّف على الأعمدة يرسل المساعد اسم كل عمود وثلاث قيم منه فقط، مع إخفاء أرقام الهاتف
              والبريد. لا يُرسل الملف كله. يمكنك دائمًا تغيير أي عمود بنفسك.
            </p>
            <div className="border-t border-line pt-4">
              <p className="mb-2 text-sm text-ink-muted">ليس لديك ملف؟ نزّل قالبًا فارغًا واملأه.</p>
              <button
                type="button"
                onClick={() => void run("template", downloadTemplate)}
                disabled={busy !== null}
                className={buttonClass("secondary")}
              >
                <Download className="size-4" aria-hidden="true" />
                تنزيل قالب فارغ
              </button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {step === "columns" && analysis ? (
        <Card>
          <CardHeader>
            <CardTitle>أي عمود هو أي بيان؟</CardTitle>
            <CardDescription>
              قرأنا {analysis.rows.length} صفًا بدءًا من الصف {analysis.first_data_row}. راجع كل عمود وغيّره إن لزم.
              {analysis.assistant_used ? " اقترح المساعد بعض الأعمدة." : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-5">
            {analysis.sheet_names.length > 1 && file ? (
              <div className="flex flex-wrap items-center gap-2">
                <label htmlFor="import-sheet" className="text-sm font-medium text-ink">
                  الورقة
                </label>
                <select
                  id="import-sheet"
                  value={analysis.sheet}
                  onChange={(event) => void analyze(file, event.target.value)}
                  className={cn(selectClass, "w-auto min-w-40")}
                >
                  {analysis.sheet_names.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <ul className="divide-y divide-line rounded-md border border-line">
              {analysis.columns.map((column) => (
                <li key={column.index} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                  <div className="min-w-0 flex-1 basis-56">
                    <p className="text-sm font-medium text-ink">{column.header}</p>
                    <p className="truncate text-xs text-ink-muted">
                      {column.samples.length > 0 ? column.samples.join("  |  ") : "لا توجد قيم"}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    {mapping[column.index] && column.field === mapping[column.index] && column.source ? (
                      <Badge variant={column.source === "ai" ? "warning" : "neutral"}>
                        {column.source === "ai" ? (
                          <>
                            <Sparkles className="size-3" aria-hidden="true" />
                            اقترحه المساعد
                          </>
                        ) : (
                          "من العنوان"
                        )}
                      </Badge>
                    ) : null}
                    <select
                      value={mapping[column.index] ?? ""}
                      onChange={(event) => setField(column.index, event.target.value as ImportField | "")}
                      aria-label={`نوع العمود ${column.header}`}
                      className={cn(selectClass, "w-44")}
                    >
                      <option value="">تجاهل هذا العمود</option>
                      {FIELD_ORDER.map((field) => (
                        <option key={field} value={field}>
                          {FIELD_LABELS[field]}
                        </option>
                      ))}
                    </select>
                  </div>
                </li>
              ))}
            </ul>

            {!hasName ? <FormError>اختر العمود الذي يحتوي على اسم الصنف.</FormError> : null}

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <label htmlFor="import-unit" className="block text-[13px] font-medium text-ink">
                  الوحدة عند عدم ذكرها
                </label>
                <select
                  id="import-unit"
                  value={options.default_unit_id ?? ""}
                  onChange={(event) =>
                    setOptions({ ...options, default_unit_id: event.target.value || null })
                  }
                  className={selectClass}
                >
                  {units.map((unit) => (
                    <option key={unit.id} value={unit.id}>
                      {unit.name_ar}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-2 text-sm text-ink">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={options.create_categories}
                    onChange={(event) => setOptions({ ...options, create_categories: event.target.checked })}
                    className="size-4 accent-brand-700"
                  />
                  إنشاء التصنيفات الجديدة تلقائيًا
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={options.create_brands}
                    onChange={(event) => setOptions({ ...options, create_brands: event.target.checked })}
                    className="size-4 accent-brand-700"
                  />
                  إنشاء الشركات الجديدة تلقائيًا
                </label>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void showPreview()}
                disabled={!hasName || busy !== null}
                className={buttonClass("primary")}
              >
                {busy === "preview" ? "جارٍ المعاينة…" : "معاينة"}
              </button>
              <button type="button" onClick={() => setStep("file")} className={buttonClass("secondary")}>
                اختيار ملف آخر
              </button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      {step === "preview" && preview ? (
        <div className="space-y-5">
          <div className="grid grid-cols-3 divide-x divide-x-reverse divide-line rounded-lg border border-line bg-panel text-center">
            {(
              [
                ["ستُنشأ", preview.counts.create, "text-brand-700"],
                ["ستُتجاهل", preview.counts.skip, "text-ink-muted"],
                ["بها مشاكل", preview.counts.error, preview.counts.error > 0 ? "text-red-700" : "text-ink-muted"],
              ] as const
            ).map(([label, value, tone]) => (
              <div key={label} className="px-3 py-4">
                <p className={cn("text-2xl font-semibold tabular-nums", tone)}>{value}</p>
                <p className="text-xs text-ink-muted">{label}</p>
              </div>
            ))}
          </div>

          {preview.notices.map((notice) => (
            <FormNotice key={notice}>{notice}</FormNotice>
          ))}
          {preview.new_categories.length > 0 || preview.new_brands.length > 0 ? (
            <FormNotice>
              {[
                preview.new_categories.length > 0 ? `تصنيفات جديدة: ${preview.new_categories.join("، ")}` : "",
                preview.new_brands.length > 0 ? `شركات جديدة: ${preview.new_brands.join("، ")}` : "",
              ]
                .filter(Boolean)
                .join(". ")}
            </FormNotice>
          ) : null}

          {problems.length > 0 ? (
            <section className="space-y-2">
              <h3 className="text-[15px] font-semibold text-red-700">صفوف بها مشاكل ({problems.length})</h3>
              <Card className="max-h-72 overflow-y-auto">
                <ul className="divide-y divide-line text-sm">
                  {problems.map((row) => (
                    <li key={row.row_number} className="px-4 py-2.5">
                      <span className="tabular-nums text-ink-muted">الصف {row.row_number}</span>
                      {row.name_ar ? <span className="ms-2 text-ink">{row.name_ar}</span> : null}
                      <span className="block text-red-700">{row.reason_ar}</span>
                    </li>
                  ))}
                </ul>
              </Card>
              <label className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={options.skip_errors}
                  onChange={(event) => setOptions({ ...options, skip_errors: event.target.checked })}
                  className="size-4 accent-brand-700"
                />
                تجاهل هذه الصفوف وإنشاء الباقي
              </label>
            </section>
          ) : null}

          {skipped.length > 0 ? (
            <details className="rounded-lg border border-line bg-panel">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-ink">
                صفوف ستُتجاهل ({skipped.length})
              </summary>
              <ul className="max-h-64 divide-y divide-line overflow-y-auto border-t border-line text-sm">
                {skipped.map((row) => (
                  <li key={row.row_number} className="px-4 py-2">
                    <span className="tabular-nums text-ink-muted">الصف {row.row_number}</span>
                    {row.name_ar ? <span className="ms-2 text-ink">{row.name_ar}</span> : null}
                    <span className="block text-xs text-ink-muted">{row.reason_ar}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}

          {creating.length > 0 ? (
            <section className="space-y-2">
              <h3 className="text-[15px] font-semibold text-ink">
                ما سيُضاف ({creating.length})
                {creating.length > 20 ? <span className="ms-2 text-xs font-normal text-ink-muted">أول 20 صفًا</span> : null}
              </h3>
              <Card className="overflow-hidden">
                <ul className="divide-y divide-line text-sm">
                  {creating.slice(0, 20).map((row) => (
                    <li key={row.row_number} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5">
                      <span className="min-w-0 flex-1 basis-48 font-medium text-ink">{row.name_ar}</span>
                      <span className="text-xs text-ink-muted" dir="ltr">
                        {row.sku}
                      </span>
                      <span className="text-xs text-ink-muted">
                        {row.quantity !== null ? `${formatQuantity(row.quantity)} ${row.unit_name_ar ?? ""}` : "بلا رصيد"}
                      </span>
                      {row.warnings.map((warning) => (
                        <span key={warning} className="basis-full text-xs text-accent-700">
                          {warning}
                        </span>
                      ))}
                    </li>
                  ))}
                </ul>
              </Card>
            </section>
          ) : null}

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void create()}
              disabled={!canCreate || busy !== null}
              className={buttonClass("primary")}
            >
              {busy === "commit" ? "جارٍ الإنشاء…" : `إنشاء ${preview.counts.create} منتج`}
            </button>
            <button type="button" onClick={() => setStep("columns")} className={buttonClass("secondary")}>
              العودة للأعمدة
            </button>
          </div>
          {busy === "commit" ? (
            <p className="text-sm text-ink-muted" role="status">
              قد يستغرق هذا بضع ثوانٍ للملفات الكبيرة. لا تغلق الصفحة.
            </p>
          ) : null}
        </div>
      ) : null}

      {step === "done" && result ? (
        <Card>
          <CardHeader>
            <CardTitle>تم الاستيراد</CardTitle>
            <CardDescription>
              {result.created === 0
                ? "لم يُضف شيء: كل المنتجات موجودة بالفعل."
                : `أُنشئ ${result.created} منتج وسُجّل رصيد افتتاحي لـ ${result.opening_balances} منها.`}
              {result.skipped > 0 ? ` تجاهلنا ${result.skipped} صفًا.` : ""}
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            <Link href="/products" className={buttonClass("primary")}>
              فتح المنتجات
            </Link>
            <Link href="/inventory" className={buttonClass("secondary")}>
              فتح المخزون
            </Link>
            <button
              type="button"
              onClick={() => {
                setStep("file");
                setAnalysis(null);
                setPreview(null);
                setResult(null);
              }}
              className={buttonClass("ghost")}
            >
              استيراد ملف آخر
            </button>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
