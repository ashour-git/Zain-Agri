"use client";

import { MessagesSquare } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

import type { Chat, Message } from "@/components/assistant/types";
import { buttonClass } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api";
import { MAX_QUESTION_CHARS, askAssistant, getAssistantStatus } from "@/lib/assistant";
import { useAuth } from "@/lib/auth-provider";

const FALLBACK_ERROR = "المساعد مش متاح دلوقتي، جرّب كمان شوية.";

const loadPanel = () => import("@/components/assistant/assistant-chat");

/** The panel (chat UI, rich text) downloads on first open or on hover/focus. */
const AssistantPanel = dynamic(() => loadPanel().then((module) => module.AssistantPanel), {
  ssr: false,
});

/**
 * The conversation lives above the panel so closing and reopening keeps it
 * (and an answer that arrives after closing is not lost). Reset on reload.
 */
function useChat(onRemaining: (remaining: number) => void): Chat {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async (history: Message[]) => {
    setPending(true);
    setError(null);
    try {
      const result = await askAssistant(history.map(({ role, content }) => ({ role, content })));
      setMessages([...history, { role: "assistant", content: result.reply, sources: result.sources }]);
      onRemaining(result.remaining_today);
    } catch (caught) {
      setError(caught instanceof ApiRequestError ? caught.message : FALLBACK_ERROR);
    } finally {
      setPending(false);
    }
  };

  const ask = (text: string) => {
    const question = text.trim().slice(0, MAX_QUESTION_CHARS);
    if (!question || pending) return;
    const history: Message[] = [...messages, { role: "user", content: question }];
    setMessages(history);
    setDraft("");
    void send(history);
  };

  return { messages, draft, setDraft, pending, error, ask, retry: () => void send(messages) };
}

/** Header button; renders nothing unless the assistant is enabled for this shop. */

/** Header button; renders nothing unless the assistant is enabled for this shop. */
export function AssistantButton() {
  const { session } = useAuth();
  const tenantId = session?.tenant?.id ?? "";
  const [status, setStatus] = useState<{ tenantId: string; enabled: boolean; remaining: number } | null>(
    null,
  );
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const chat = useChat((remaining) =>
    setStatus((current) => (current ? { ...current, remaining } : current)),
  );

  useEffect(() => {
    if (!tenantId) return;
    let cancelled = false;
    void getAssistantStatus()
      .then((next) => {
        if (!cancelled) setStatus({ tenantId, enabled: next.enabled, remaining: next.remaining_today });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [tenantId]);

  if (!status || status.tenantId !== tenantId || !status.enabled) return null;

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        onClick={() => setOpen(true)}
        // Start downloading the panel as soon as the user shows intent.
        onPointerEnter={() => void loadPanel()}
        onFocus={() => void loadPanel()}
        aria-haspopup="dialog"
        aria-expanded={open}
        className={buttonClass("secondary", "md", "gap-2 px-3")}
      >
        <MessagesSquare className="size-[18px] text-brand-700" aria-hidden="true" />
        <span className="hidden sm:inline">اسأل المساعد</span>
        <span className="sr-only sm:hidden">اسأل المساعد</span>
      </button>
      {open ? (
        <AssistantPanel chat={chat} remaining={status.remaining} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}
