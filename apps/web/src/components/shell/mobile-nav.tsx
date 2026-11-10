"use client";

import { Menu, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { useCallback, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { BrandMark, BrandWordmark } from "@/components/brand";
import { NavLists } from "@/components/shell/nav";
import { WorkspaceSwitch } from "@/components/shell/sidebar";
import { useDialog } from "@/components/ui/use-dialog";

/** Slide-in navigation for screens narrower than the desktop sidebar (< lg). */
export function MobileNav({ workspaceName }: { workspaceName: string }) {
  // Remember which route the drawer was opened on: any navigation (a link,
  // browser back/forward) makes it stale, which closes it without an effect.
  const pathname = usePathname();
  const [openedOn, setOpenedOn] = useState<string | null>(null);
  const open = openedOn === pathname;
  const panelRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => setOpenedOn(null), []);
  useDialog(open, close, panelRef);

  return (
    <div className="lg:hidden">
      <button
        type="button"
        onClick={() => setOpenedOn(pathname)}
        aria-label="فتح القائمة"
        aria-expanded={open}
        aria-controls="mobile-nav"
        className="grid size-10 place-items-center rounded-md border border-line-strong bg-panel text-ink transition-colors hover:bg-brand-50"
      >
        <Menu className="size-5" aria-hidden="true" />
      </button>

      {/* Portal to <body>: the sticky header uses backdrop-blur, which would
          otherwise become the containing block and clip this fixed overlay. */}
      {open
        ? createPortal(
            <div className="fixed inset-0 z-50 animate-fade-in bg-ink/40" onClick={close}>
              <div
                id="mobile-nav"
                ref={panelRef}
                role="dialog"
                aria-modal="true"
                aria-label="القائمة الرئيسية"
                tabIndex={-1}
                onClick={(event) => event.stopPropagation()}
                className="absolute inset-y-0 right-0 flex w-[min(18rem,85vw)] animate-slide-in flex-col bg-panel pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] shadow-2xl outline-none"
              >
                <div className="flex items-center gap-3 px-5 py-5">
                  <BrandMark />
                  <BrandWordmark />
                  <button
                    type="button"
                    onClick={close}
                    aria-label="إغلاق القائمة"
                    className="ms-auto grid size-10 place-items-center rounded-md text-ink-muted transition-colors hover:bg-surface hover:text-ink"
                  >
                    <X className="size-5" aria-hidden="true" />
                  </button>
                </div>
                <WorkspaceSwitch workspaceName={workspaceName} />
                <NavLists onNavigate={close} />
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
