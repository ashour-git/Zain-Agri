import { LogOut } from "lucide-react";

import { AssistantButton } from "@/components/assistant/assistant-panel";
import { MobileNav } from "@/components/shell/mobile-nav";
import { ROLE_LABELS, type MembershipRole } from "@/lib/types";

export function Header({
  title,
  workspaceName,
  userInitial,
  userName,
  role,
  onSignOut,
}: {
  title: string;
  workspaceName: string;
  userInitial: string;
  userName: string;
  role: MembershipRole | null;
  onSignOut: () => void;
}) {
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-surface/90 backdrop-blur">
      <div className="flex h-16 items-center gap-3 px-4 sm:px-8">
        <MobileNav workspaceName={workspaceName} />

        <h1 className="min-w-0 truncate text-lg font-semibold text-ink">{title}</h1>

        <div className="ms-auto flex items-center gap-2">
          <AssistantButton />
          <div className="hidden items-center gap-2.5 sm:flex">
            <span
              className="grid size-9 place-items-center rounded-full bg-brand-100 text-sm font-semibold text-brand-800"
              aria-hidden="true"
            >
              {userInitial}
            </span>
            <span className="leading-tight">
              <span className="block max-w-40 truncate text-sm font-medium text-ink">{userName}</span>
              {role ? <span className="block text-xs text-ink-muted">{ROLE_LABELS[role]}</span> : null}
            </span>
          </div>

          <button
            type="button"
            onClick={onSignOut}
            className="grid size-10 place-items-center rounded-md text-ink-muted transition-colors hover:bg-red-50 hover:text-red-700"
            title="تسجيل الخروج"
            aria-label="تسجيل الخروج"
          >
            <LogOut className="size-[18px]" aria-hidden="true" />
          </button>
        </div>
      </div>
    </header>
  );
}
