"use client";

/*
 * The chat panel itself. Loaded on demand by AssistantButton (next/dynamic),
 * so pages that never open the assistant don't download it.
 */

import { MessagesSquare, RotateCcw, Send, X } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";

import { RichText } from "@/components/assistant/rich-text";
import type { Chat } from "@/components/assistant/types";
import { buttonClass } from "@/components/ui/button";
import { useDialog } from "@/components/ui/use-dialog";
import { MAX_QUESTION_CHARS } from "@/lib/assistant";
import { useAuth } from "@/lib/auth-provider";
import { cn } from "@/lib/utils";

const STARTERS: { text: string; permission: string }[] = [
  { text: "إيه الأصناف اللي محتاج أطلبها؟", permission: "inventory.read" },
  { text: "إيه اللي صلاحيته هتخلص الشهر ده؟", permission: "inventory.read" },
  { text: "إيه اللي اتحرك في المخزن الأسبوع ده؟", permission: "inventory.read" },
];

export function AssistantPanel({
  chat,
  remaining,
  onClose,
}: {
  chat: Chat;
  remaining: number;
  onClose: () => void;
}) {
  const { messages, draft, setDraft, pending, error, ask, retry } = chat;
  const { session } = useAuth();
  const permissions = session?.permissions ?? [];
  const starters = STARTERS.filter((starter) => permissions.includes(starter.permission));

  const panelRef = useRef<HTMLDivElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const close = useCallback(() => onClose(), [onClose]);
  useDialog(true, close, panelRef);

  // Keep the newest message in view.
  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages.length, pending, error]);

  return createPortal(
    <div className="fixed inset-0 z-50 animate-fade-in bg-ink/30" onMouseDown={close}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="assistant-title"
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
        className="absolute inset-y-0 end-0 flex w-full animate-slide-in-end flex-col bg-panel pb-[env(safe-area-inset-bottom)] pt-[env(safe-area-inset-top)] shadow-2xl outline-none sm:w-[400px]"
      >
        <div className="flex h-16 shrink-0 items-center gap-3 border-b border-line px-5">
          <MessagesSquare className="size-5 text-brand-700" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <h2 id="assistant-title" className="text-base font-semibold text-ink">
              المساعد
            </h2>
            <p className="text-xs text-ink-muted">بيقرا بيانات متجرك بس، وما بيغيّرش حاجة.</p>
          </div>
          <button
            type="button"
            onClick={close}
            aria-label="إغلاق المساعد"
            className="grid size-10 place-items-center rounded-md text-ink-muted transition-colors hover:bg-surface hover:text-ink"
          >
            <X className="size-5" aria-hidden="true" />
          </button>
        </div>

        <div ref={listRef} className="flex-1 space-y-5 overflow-y-auto px-5 py-5" aria-live="polite">
          {messages.length === 0 ? (
            <div className="space-y-4">
              <p className="text-sm leading-relaxed text-ink-muted">
                اسأل عن رصيد صنف، النواقص، الحركات، أو الصلاحية.
              </p>
              {starters.length > 0 ? (
                <div className="flex flex-col items-start gap-2">
                  {starters.map((starter) => (
                    <button
                      key={starter.text}
                      type="button"
                      onClick={() => ask(starter.text)}
                      className="rounded-full border border-line-strong px-3.5 py-2 text-start text-sm text-ink transition-colors hover:border-brand-400 hover:bg-brand-50"
                    >
                      {starter.text}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {messages.map((message, index) =>
            message.role === "user" ? (
              <div key={index} className="flex justify-end">
                <p className="max-w-[85%] whitespace-pre-wrap rounded-lg rounded-ee-sm bg-brand-700 px-3.5 py-2.5 text-sm leading-relaxed text-white">
                  {message.content}
                </p>
              </div>
            ) : (
              <div key={index} className="space-y-1.5 text-sm text-ink">
                <RichText text={message.content} />
                {message.sources && message.sources.length > 0 ? (
                  <p className="text-xs text-ink-muted">
                    من بيانات متجرك: {message.sources.map((source) => source.label).join("، ")}
                  </p>
                ) : null}
              </div>
            ),
          )}

          {pending ? (
            <div className="flex gap-1.5 py-1" role="status" aria-label="المساعد بيكتب">
              {[0, 150, 300].map((delay) => (
                <span
                  key={delay}
                  className="size-2 animate-pulse rounded-full bg-ink-muted/50"
                  style={{ animationDelay: `${delay}ms` }}
                />
              ))}
            </div>
          ) : null}

          {error ? (
            <div role="alert" className="space-y-2 rounded-md border border-red-200 bg-red-50 px-3.5 py-3">
              <p className="text-sm text-red-800">{error}</p>
              <button type="button" onClick={retry} className={buttonClass("secondary", "sm")}>
                <RotateCcw className="size-3.5" aria-hidden="true" />
                إعادة المحاولة
              </button>
            </div>
          ) : null}
        </div>

        <form
          className="shrink-0 border-t border-line px-4 pb-3 pt-3"
          onSubmit={(event) => {
            event.preventDefault();
            ask(draft);
          }}
        >
          <div className="flex items-end gap-2">
            <label htmlFor="assistant-input" className="sr-only">
              سؤالك
            </label>
            <textarea
              id="assistant-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  ask(draft);
                }
              }}
              rows={1}
              maxLength={MAX_QUESTION_CHARS}
              placeholder="اكتب سؤالك…"
              className="max-h-32 min-h-11 flex-1 resize-none rounded-md border border-line-strong bg-panel px-3 py-2.5 text-sm text-ink outline-none transition-colors placeholder:text-ink-muted/70 focus:border-brand-600 focus:ring-2 focus:ring-brand-100 [field-sizing:content]"
            />
            <button
              type="submit"
              disabled={pending || !draft.trim()}
              className={buttonClass("primary", "md", "size-11 px-0")}
              aria-label="إرسال"
            >
              <Send className="size-[18px] -scale-x-100" aria-hidden="true" />
            </button>
          </div>
          <p className={cn("mt-2 text-xs", remaining <= 5 ? "text-accent-700" : "text-ink-muted")}>
            <span className="tabular">{remaining}</span> سؤال متبقي النهارده
          </p>
        </form>
      </div>
    </div>,
    document.body,
  );
}
