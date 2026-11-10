import { ArrowLeftRight } from "lucide-react";
import Link from "next/link";

import { BrandMark, BrandWordmark } from "@/components/brand";
import { NavLists } from "@/components/shell/nav";

/** The store being worked on, with the way to switch to another one. */
export function WorkspaceSwitch({ workspaceName }: { workspaceName: string }) {
  return (
    <Link
      href="/select-tenant"
      className="group mx-3 mb-4 flex items-center gap-3 rounded-md border border-line px-3 py-2.5 transition-colors hover:border-brand-300 hover:bg-brand-50"
    >
      <span className="min-w-0 flex-1">
        <span className="block text-xs text-ink-muted">المتجر الحالي</span>
        <span className="block truncate text-sm font-medium text-ink">{workspaceName}</span>
      </span>
      <ArrowLeftRight className="size-4 shrink-0 text-ink-muted group-hover:text-brand-700" aria-hidden="true" />
      <span className="sr-only">تبديل المتجر</span>
    </Link>
  );
}

export function Sidebar({ workspaceName }: { workspaceName: string }) {
  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-e border-line bg-panel lg:flex">
      <div className="flex items-center gap-3 px-6 pb-5 pt-6">
        <BrandMark />
        <BrandWordmark />
      </div>
      <WorkspaceSwitch workspaceName={workspaceName} />
      <NavLists />
    </aside>
  );
}
