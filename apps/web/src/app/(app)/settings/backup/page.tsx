"use client";

import { DatabaseBackup, Send } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { buttonClass } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, FormError, FormNotice } from "@/components/ui/field";
import { ApiRequestError } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import {
  type BackupState,
  formatSentAt,
  getBackup,
  saveBackupEmail,
  sendBackupNow,
  stopBackup,
} from "@/lib/backup";

function messageOf(caught: unknown, fallback: string): string {
  return caught instanceof ApiRequestError ? caught.message : fallback;
}

function StatusLine({ state }: { state: BackupState }) {
  if (state.last_error_ar && state.status === "active") {
    return (
      <p className="flex flex-wrap items-center gap-2 text-sm text-red-700">
        <Badge variant="danger">تنبيه</Badge>
        فشل الإرسال الأخير: {state.last_error_ar}
      </p>
    );
  }
  if (state.status === "pending") {
    return (
      <p className="flex flex-wrap items-center gap-2 text-sm text-ink">
        <Badge variant="warning">في الانتظار</Badge>
        في انتظار التأكيد، راجع بريدك.
      </p>
    );
  }
  if (state.status === "active") {
    return (
      <p className="flex flex-wrap items-center gap-2 text-sm text-ink">
        <Badge variant="brand">مفعّلة</Badge>
        {state.last_sent_at
          ? `آخر نسخة أُرسلت: ${formatSentAt(state.last_sent_at)}`
          : "مفعّلة. تصلك أول نسخة الليلة."}
      </p>
    );
  }
  return (
    <p className="flex flex-wrap items-center gap-2 text-sm text-ink-muted">
      <Badge variant="neutral">غير مفعّلة</Badge>
      {state.status === "stopped" ? "النسخة اليومية موقوفة." : "لم يُفعَّل بعد."}
    </p>
  );
}

function LoadingCard() {
  return (
    <Card aria-busy="true">
      <CardContent className="space-y-4 pt-5 motion-safe:animate-pulse">
        <span className="block h-4 w-40 rounded bg-line/70" />
        <span className="block h-10 w-full rounded bg-line/70" />
        <span className="block h-9 w-48 rounded bg-line/70" />
      </CardContent>
    </Card>
  );
}

export default function BackupSettingsPage() {
  const { session } = useAuth();
  const [state, setState] = useState<BackupState | null>(null);
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "send" | "stop" | null>(null);

  useEffect(() => {
    let cancelled = false;
    getBackup()
      .then((loaded) => {
        if (cancelled) return;
        setState(loaded);
        setEmail(loaded.email ?? session?.user.email ?? "");
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(messageOf(caught, "تعذّر تحميل الإعدادات. حاول مرة أخرى."));
      });
    return () => {
      cancelled = true;
    };
  }, [session?.user.email]);

  async function run(kind: "save" | "send" | "stop", action: () => Promise<void>) {
    setBusy(kind);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (caught) {
      setError(messageOf(caught, "تعذّر إكمال الطلب. حاول مرة أخرى."));
    } finally {
      setBusy(null);
    }
  }

  const onSave = (event: FormEvent) => {
    event.preventDefault();
    void run("save", async () => {
      const saved = await saveBackupEmail(email);
      setState(saved);
      setNotice(
        saved.status === "pending"
          ? `أرسلنا رابط التأكيد إلى ${saved.email}. افتحه خلال 24 ساعة.`
          : "العنوان محفوظ ومؤكَّد.",
      );
    });
  };

  const onSend = () =>
    void run("send", async () => {
      const sent = await sendBackupNow();
      setState(sent);
      setNotice(sent.last_error_ar ? null : `أُرسلت النسخة إلى ${sent.email}.`);
      if (sent.last_error_ar) setError(`فشل الإرسال: ${sent.last_error_ar}`);
    });

  const onStop = () =>
    void run("stop", async () => {
      await stopBackup();
      setState(await getBackup());
      setNotice("أوقفنا النسخة اليومية. يمكنك تفعيلها مرة أخرى بحفظ العنوان.");
    });

  const active = state?.status === "active";
  const canStop = state?.status === "active" || state?.status === "pending";

  return (
    <div className="mx-auto w-full max-w-3xl space-y-6 px-5 py-8 sm:px-8">
      <FormError>{error}</FormError>
      <FormNotice>{notice}</FormNotice>

      {state === null ? (
        error ? null : <LoadingCard />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <DatabaseBackup className="size-4 text-brand-600" aria-hidden="true" />
              النسخة اليومية
            </CardTitle>
            <CardDescription>
              قبل فجر كل يوم يصلك ملف Excel فيه منتجات متجرك ورصيدها وحركاتها وسجل
              النشاط. الملف يخص متجرك وحده.
            </CardDescription>
          </CardHeader>

          <CardContent className="space-y-6">
            <StatusLine state={state} />

            {!state.mail_configured ? (
              <FormError>الإرسال غير مُعدّ. تواصل مع مسؤول النظام لتفعيله.</FormError>
            ) : null}

            <form onSubmit={onSave} className="space-y-3 border-t border-line pt-5">
              <Field
                label="البريد الذي تصله النسخة"
                name="backup-email"
                type="email"
                dir="ltr"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                hint="نرسل رابط تأكيد أولًا، ولا تصل أي بيانات قبل الضغط عليه."
              />
              <button
                type="submit"
                disabled={busy !== null || !state.mail_configured}
                className={buttonClass("primary")}
              >
                {busy === "save" ? "جارٍ الحفظ…" : "حفظ وإرسال رابط التأكيد"}
              </button>
            </form>

            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
              <button
                type="button"
                onClick={onSend}
                disabled={busy !== null || !active || state.manual_sends_left === 0}
                className={buttonClass("secondary")}
              >
                <Send className="size-4" aria-hidden="true" />
                {busy === "send" ? "جارٍ الإرسال…" : "أرسل نسخة الآن"}
              </button>
              <span className="text-xs text-ink-muted">
                متبقٍ اليوم: {state.manual_sends_left} من 3
              </span>
              {canStop ? (
                <button
                  type="button"
                  onClick={onStop}
                  disabled={busy !== null}
                  className={buttonClass("danger", "md", "ms-auto")}
                >
                  {busy === "stop" ? "جارٍ الإيقاف…" : "إيقاف النسخة اليومية"}
                </button>
              ) : null}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
