"use client";

import { Info } from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import { cn } from "@/lib/utils";

/**
 * A field label with an (i) button that opens a plain-language explanation
 * under it. Opens on tap (phones have no hover) and closes with Escape.
 */
export function FieldLabel({
  htmlFor,
  label,
  info,
  className,
}: {
  htmlFor?: string;
  label: ReactNode;
  info?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5">
        {htmlFor ? (
          <label htmlFor={htmlFor} className={cn("block text-[13px] font-medium text-ink", className)}>
            {label}
          </label>
        ) : (
          <span className={cn("block text-[13px] font-medium text-ink", className)}>{label}</span>
        )}
        {info ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && open) {
                event.stopPropagation();
                setOpen(false);
              }
            }}
            aria-expanded={open}
            aria-controls={panelId}
            aria-label={`ما معنى «${typeof label === "string" ? label.replace(/\s*\*$/, "") : "هذا"}»؟`}
            className={cn(
              "grid size-5 shrink-0 place-items-center rounded-full transition-colors",
              open ? "bg-brand-700 text-white" : "text-ink-muted hover:bg-brand-50 hover:text-brand-700",
            )}
          >
            <Info className="size-3.5" aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {info ? (
        <p
          id={panelId}
          hidden={!open}
          className="rounded-md border border-brand-100 bg-brand-50 px-3 py-2 text-xs leading-relaxed text-brand-900"
        >
          {info}
        </p>
      ) : null}
    </div>
  );
}

/** The same (i) explanation for something that is not a form field (a checkbox, a section). */
export function InfoNote({ title, info }: { title: ReactNode; info: string }) {
  return <FieldLabel label={title} info={info} />;
}
