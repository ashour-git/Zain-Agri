"use client";

import { useEffect, useRef, type RefObject } from "react";

/** Open dialogs, innermost last. */
const openStack: symbol[] = [];

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Behaviour every modal surface needs: Escape closes, the page behind does not
 * scroll, focus moves inside on open, Tab cannot leave, and focus returns to the
 * element that opened it on close.
 */
export function useDialog(open: boolean, onClose: () => void, ref: RefObject<HTMLElement | null>) {
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const container = ref.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const focusables = () =>
      container ? Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];

    // Prefer the first form control so typing can start at once; fall back to the container.
    const firstField = container?.querySelector<HTMLElement>(
      "input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled])",
    );
    (firstField ?? container)?.focus({ preventScroll: true });

    const token = Symbol("dialog");
    openStack.push(token);

    const onKeyDown = (event: KeyboardEvent) => {
      // Stacked dialogs (a batch form over a product's history): only the top one listens.
      if (openStack.at(-1) !== token) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusables();
      const first = items[0];
      const last = items.at(-1);
      if (!first || !last) {
        event.preventDefault();
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      openStack.splice(openStack.indexOf(token), 1);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus?.({ preventScroll: true });
    };
  }, [open, ref]);
}
