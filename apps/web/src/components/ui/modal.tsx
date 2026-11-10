"use client";

import { X } from "lucide-react";
import { useId, useRef, type ReactNode } from "react";

import { useDialog } from "@/components/ui/use-dialog";
import { cn } from "@/lib/utils";

export function Modal({
  open,
  title,
  description,
  onClose,
  children,
  wide,
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useDialog(open, onClose, panelRef);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center overflow-y-auto bg-brand-950/40 p-0 animate-fade-in sm:items-start sm:p-8"
      onMouseDown={(event) => {
        // Close only when the press starts on the backdrop itself, so a text
        // selection that ends outside the panel does not discard the form.
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={cn(
          "w-full rounded-t-2xl border border-line bg-white shadow-xl outline-none sm:my-auto sm:rounded-lg",
          "max-h-[92dvh] overflow-y-auto pb-[env(safe-area-inset-bottom)] sm:max-h-none",
          wide ? "sm:max-w-3xl" : "sm:max-w-xl",
        )}
      >
        <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-line bg-white px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-base font-bold text-ink">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="mt-0.5 text-xs leading-relaxed text-ink-muted">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="إغلاق"
            className="grid size-10 shrink-0 place-items-center rounded-lg text-ink-muted transition-colors hover:bg-surface hover:text-ink"
          >
            <X className="size-4" aria-hidden="true" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  );
}
