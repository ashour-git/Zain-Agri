"use client";

import { CircleAlert, MailCheck } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { BrandMark, BrandWordmark } from "@/components/brand";
import { buttonClass } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api";
import { confirmBackupEmail } from "@/lib/backup";

type Outcome = { kind: "working" } | { kind: "done" } | { kind: "failed"; message: string };

const MISSING_TOKEN = "الرابط ناقص. افتحه من رسالة التأكيد كما هو.";

function ConfirmResult() {
  const token = useSearchParams().get("token");
  const [outcome, setOutcome] = useState<Outcome>(
    token ? { kind: "working" } : { kind: "failed", message: MISSING_TOKEN },
  );
  // The link works once; React's dev double-effect must not spend it twice.
  const sent = useRef(false);

  useEffect(() => {
    if (!token || sent.current) return;
    sent.current = true;
    confirmBackupEmail(token)
      .then(() => setOutcome({ kind: "done" }))
      .catch((caught: unknown) =>
        setOutcome({
          kind: "failed",
          message:
            caught instanceof ApiRequestError
              ? caught.message
              : "تعذّر تأكيد البريد. تحقق من اتصالك ثم أعد فتح الرابط.",
        }),
      );
  }, [token]);

  if (outcome.kind === "working") {
    return (
      <p role="status" className="text-sm text-ink-muted">
        جارٍ تأكيد البريد…
      </p>
    );
  }

  const done = outcome.kind === "done";
  const Icon = done ? MailCheck : CircleAlert;
  return (
    <div role={done ? "status" : "alert"} className="space-y-4">
      <Icon
        className={`size-7 ${done ? "text-brand-700" : "text-red-700"}`}
        aria-hidden="true"
      />
      <h1 className="text-[22px] font-semibold leading-snug text-ink">
        {done ? "تم تأكيد البريد" : "لم يتم التأكيد"}
      </h1>
      <p className="text-sm leading-relaxed text-ink-muted">
        {done ? "ستصلك أول نسخة من بيانات متجرك قبل فجر الغد." : outcome.message}
      </p>
      <Link href="/settings/backup" className={buttonClass("primary")}>
        {done ? "فتح إعدادات النسخة اليومية" : "الذهاب إلى الإعدادات"}
      </Link>
    </div>
  );
}

export default function ConfirmBackupPage() {
  return (
    <div className="flex min-h-dvh flex-col px-5 py-8 sm:px-10">
      <div className="flex items-center gap-3">
        <BrandMark />
        <BrandWordmark />
      </div>
      <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center py-12">
        <Suspense
          fallback={
            <p role="status" className="text-sm text-ink-muted">
              جارٍ تأكيد البريد…
            </p>
          }
        >
          <ConfirmResult />
        </Suspense>
      </main>
    </div>
  );
}
