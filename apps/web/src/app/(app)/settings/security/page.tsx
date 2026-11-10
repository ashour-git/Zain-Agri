"use client";

import {
  Building2,
  Clock,
  KeyRound,
  LogOut,
  Mail,
  Monitor,
  ShieldCheck,
  Trash2,
  User,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { FormError } from "@/components/ui/field";
import { ApiRequestError, apiRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-provider";
import {
  PERMISSION_LABELS,
  ROLE_LABELS,
  type MembershipRole,
  type SessionInfo,
} from "@/lib/types";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("ar-EG-u-nu-latn", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function deviceLabel(userAgent: string | null): string {
  if (!userAgent) return "جهاز غير معروف";
  const browser = /Edg\//.test(userAgent)
    ? "Edge"
    : /Chrome\//.test(userAgent)
      ? "Chrome"
      : /Firefox\//.test(userAgent)
        ? "Firefox"
        : /Safari\//.test(userAgent)
          ? "Safari"
          : "متصفح";
  const os = /Windows/.test(userAgent)
    ? "Windows"
    : /Android/.test(userAgent)
      ? "Android"
      : /iPhone|iPad/.test(userAgent)
        ? "iOS"
        : /Mac OS X/.test(userAgent)
          ? "macOS"
          : /Linux/.test(userAgent)
            ? "Linux"
            : "";
  return os ? `${browser} على ${os}` : browser;
}

function Row({
  icon: Icon,
  label,
  value,
  mono,
}: {
  icon: typeof User;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-start gap-3 rounded-md border border-line bg-white px-4 py-3">
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
        <Icon className="size-4" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <p className="text-xs text-ink-muted">{label}</p>
        <p
          className={`truncate text-sm font-medium text-ink ${mono ? "font-mono text-xs" : ""}`}
          dir={mono ? "ltr" : undefined}
        >
          {value}
        </p>
      </div>
    </div>
  );
}

export default function SecuritySettingsPage() {
  const { session, signOut, signOutEverywhere } = useAuth();
  const router = useRouter();

  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [revokingAll, setRevokingAll] = useState(false);

  const fetchSessions = useCallback(
    () => apiRequest<SessionInfo[]>("/api/v1/auth/sessions"),
    [],
  );

  const describe = (caught: unknown) =>
    caught instanceof ApiRequestError
      ? caught.message
      : "تعذّر تحميل الجلسات. حاول مرة أخرى.";

  useEffect(() => {
    let cancelled = false;

    void fetchSessions()
      .then((rows) => {
        if (cancelled) return;
        setSessions(rows);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!cancelled) setError(describe(caught));
      });

    return () => {
      cancelled = true;
    };
  }, [fetchSessions]);

  const revoke = async (row: SessionInfo) => {
    setBusyId(row.id);
    setError(null);
    try {
      await apiRequest<void>(`/api/v1/auth/sessions/${row.id}`, { method: "DELETE" });
      if (row.is_current) {
        // The session backing this tab is gone; returning to /login is the only
        // honest outcome.
        await signOut();
        router.replace("/login");
        return;
      }
      setSessions(await fetchSessions());
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError
          ? caught.message
          : "تعذّر إنهاء الجلسة. حاول مرة أخرى.",
      );
    } finally {
      setBusyId(null);
    }
  };

  const revokeEverywhere = async () => {
    setRevokingAll(true);
    setError(null);
    try {
      await signOutEverywhere();
      router.replace("/login");
    } catch (caught) {
      setError(
        caught instanceof ApiRequestError
          ? caught.message
          : "تعذّر إنهاء كل الجلسات. حاول مرة أخرى.",
      );
      setRevokingAll(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-4xl space-y-6 px-5 py-8 sm:px-8">
      <FormError>{error}</FormError>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <User className="size-4 text-brand-600" aria-hidden="true" />
            الحساب الحالي
          </CardTitle>
          <CardDescription>البيانات التي يعرفها الخادم عنك في هذه الجلسة.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <Row icon={User} label="الاسم" value={session?.user.full_name ?? "-"} />
          <Row icon={Mail} label="البريد الإلكتروني" value={session?.user.email ?? "-"} mono />
          <Row
            icon={Building2}
            label="مساحة العمل"
            value={session?.tenant?.name ?? "لم تُحدد بعد"}
          />
          <Row
            icon={KeyRound}
            label="الدور والصلاحيات"
            value={
              session?.role
                ? `${ROLE_LABELS[session.role as MembershipRole]} - ${session.permissions.length} صلاحية`
                : "-"
            }
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Monitor className="size-4 text-brand-600" aria-hidden="true" />
            الجلسات النشطة
          </CardTitle>
          <CardDescription>
            كل جهاز سجّل الدخول له جلسة مستقلة. إنهاء جلسة يوقف رمز الوصول المرتبط بها فوراً.
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-2.5">
          {sessions === null ? (
            <p className="rounded-md border border-dashed border-line px-4 py-6 text-center text-xs text-ink-muted">
              جارٍ تحميل الجلسات…
            </p>
          ) : sessions.length === 0 ? (
            <p className="rounded-md border border-dashed border-line px-4 py-6 text-center text-xs text-ink-muted">
              لا توجد جلسات نشطة.
            </p>
          ) : (
            sessions.map((row) => (
              <div
                key={row.id}
                className="flex flex-wrap items-center gap-3 rounded-md border border-line bg-white px-4 py-3"
              >
                <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-50 text-brand-700">
                  <Monitor className="size-4" aria-hidden="true" />
                </span>

                <div className="min-w-0 flex-1">
                  <p className="flex items-center gap-2 text-sm font-medium text-ink">
                    {deviceLabel(row.user_agent)}
                    {row.is_current ? <Badge variant="brand">هذا الجهاز</Badge> : null}
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs text-ink-muted">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="size-3" aria-hidden="true" />
                      بدأت {formatDate(row.created_at)}
                    </span>
                    <span>تنتهي {formatDate(row.expires_at)}</span>
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => {
                    void revoke(row);
                  }}
                  disabled={busyId !== null || revokingAll}
                  className="inline-flex items-center gap-1.5 min-h-9 rounded-lg border border-line px-2.5 text-xs text-ink-muted transition-colors hover:border-red-200 hover:bg-red-50 hover:text-red-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Trash2 className="size-3.5" aria-hidden="true" />
                  {busyId === row.id ? "جارٍ الإنهاء…" : "إنهاء"}
                </button>
              </div>
            ))
          )}

          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <button
              type="button"
              onClick={() => {
                void revokeEverywhere();
              }}
              disabled={revokingAll || busyId !== null}
              className="inline-flex items-center gap-2 rounded-md bg-brand-700 px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-brand-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <ShieldCheck className="size-4" aria-hidden="true" />
              {revokingAll ? "جارٍ الإنهاء…" : "إنهاء كل الجلسات"}
            </button>

            <button
              type="button"
              onClick={() => {
                void signOut().then(() => router.replace("/login"));
              }}
              className="inline-flex items-center gap-2 rounded-md border border-line px-4 py-2 text-xs text-ink-muted transition-colors hover:text-brand-700"
            >
              <LogOut className="size-4" aria-hidden="true" />
              تسجيل الخروج من هذا الجهاز
            </button>
          </div>
        </CardContent>
      </Card>

      {session?.role ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <KeyRound className="size-4 text-brand-600" aria-hidden="true" />
              صلاحيات دورك
            </CardTitle>
            <CardDescription>
              ما يمكنك فعله في هذا المتجر. لتغييرها تواصل مع مالك المتجر.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {session.permissions.map((permission) => (
              <Badge key={permission} variant="neutral">
                {PERMISSION_LABELS[permission] ?? permission}
              </Badge>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Card className="border-brand-200 bg-brand-50/60">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-brand-900">
            <ShieldCheck className="size-4" aria-hidden="true" />
            كيف نحمي جلستك
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2 text-xs leading-relaxed text-brand-900/80">
            <li>لا نحفظ رموز الدخول في مكان يمكن لأي موقع أو إضافة متصفح قراءته.</li>
            <li>تنتهي صلاحية رمز الدخول سريعاً ويتجدد تلقائياً أثناء استخدامك للتطبيق.</li>
            <li>إذا سُرق رمز قديم وحاول أحد استخدامه، تُغلق كل جلساتك فوراً.</li>
            <li>بيانات متجرك معزولة تماماً، ولا يمكن لأي متجر آخر رؤيتها.</li>
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
