"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import type { ReactNode } from "react";

import { useAuth } from "@/lib/auth-provider";

function Splash({ label }: { label: string }) {
  return (
    <div className="grid min-h-dvh place-items-center bg-surface">
      <div className="flex flex-col items-center gap-4" role="status" aria-live="polite">
        <span className="size-9 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
        <p className="text-sm text-ink-muted">{label}</p>
      </div>
    </div>
  );
}

/**
 * Client-side navigation guard.
 *
 * It exists so the interface does not flash data that the visitor may not see.
 * It is *not* the security boundary: every request is authorised again on the
 * server, where the workspace is read from the session and re-validated.
 */
export function AuthGuard({
  children,
  requireTenant = true,
  redirectIfAuthenticated = false,
  loading,
}: {
  children: ReactNode;
  requireTenant?: boolean;
  redirectIfAuthenticated?: boolean;
  /** Shown while the session is checked. Defaults to a centred spinner. */
  loading?: ReactNode;
}) {
  const { status, session } = useAuth();
  const router = useRouter();

  const needsTenant = Boolean(session?.requires_tenant_selection);

  useEffect(() => {
    if (status === "loading") return;

    if (status === "unauthenticated") {
      if (!redirectIfAuthenticated) router.replace("/login");
      return;
    }

    if (redirectIfAuthenticated) {
      router.replace(needsTenant ? "/select-tenant" : "/");
      return;
    }

    if (requireTenant && needsTenant) {
      router.replace("/select-tenant");
    }
  }, [status, needsTenant, requireTenant, redirectIfAuthenticated, router]);

  if (status === "loading") {
    // Sign-in pages hold nothing private: show them at once. A visitor who
    // turns out to be signed in is redirected by the effect above.
    if (redirectIfAuthenticated) return <>{children}</>;
    return loading ?? <Splash label="جارٍ التحقق من الجلسة…" />;
  }

  if (status === "unauthenticated") {
    return redirectIfAuthenticated ? <>{children}</> : <Splash label="جارٍ تحويلك لتسجيل الدخول…" />;
  }

  if (redirectIfAuthenticated) return <Splash label="جارٍ فتح مساحة العمل…" />;
  if (requireTenant && needsTenant) return <Splash label="اختر مساحة عمل…" />;

  return <>{children}</>;
}
