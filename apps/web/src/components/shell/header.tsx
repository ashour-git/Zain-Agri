import Link from "next/link";
import { LogOut } from "lucide-react";

import { BrandMark } from "@/components/brand";
import { Badge } from "@/components/ui/badge";
import { ROLE_LABELS, type MembershipRole } from "@/lib/types";

export function Header({
  title,
  subtitle,
  workspaceName,
  userInitial,
  role,
  onSignOut,
}: {
  title: string;
  subtitle?: string;
  workspaceName: string;
  userInitial: string;
  role: MembershipRole | null;
  onSignOut: () => void;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface/85 backdrop-blur">
      <div className="flex items-center gap-4 px-5 py-4 sm:px-8">
        <div className="lg:hidden">
          <BrandMark className="size-9" />
        </div>

        <div className="min-w-0">
          <h1 className="truncate text-lg font-bold text-ink sm:text-xl">{title}</h1>
          {subtitle ? <p className="truncate text-xs text-ink-muted">{subtitle}</p> : null}
        </div>

        <div className="ms-auto flex items-center gap-3">
          <Link
            href="/settings/security"
            className="hidden items-center gap-2 rounded-full border border-line bg-white px-3 py-1.5 sm:inline-flex"
          >
            <span className="size-1.5 rounded-full bg-accent-500" aria-hidden="true" />
            <span className="max-w-40 truncate text-xs text-ink-muted">{workspaceName}</span>
            {role ? <Badge variant="brand">{ROLE_LABELS[role]}</Badge> : null}
          </Link>

          <div
            className="grid size-9 place-items-center rounded-full bg-brand-900 text-xs font-bold text-white"
            title="المستخدم الحالي"
          >
            {userInitial}
          </div>

          <button
            type="button"
            onClick={onSignOut}
            className="grid size-9 place-items-center rounded-full border border-line bg-white text-ink-muted transition-colors hover:text-brand-700"
            title="تسجيل الخروج"
            aria-label="تسجيل الخروج"
          >
            <LogOut className="size-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  );
}
