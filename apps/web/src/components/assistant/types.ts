import type { ChatSource, ChatTurn } from "@/lib/assistant";

export type Message = ChatTurn & { sources?: ChatSource[] };

export type Chat = {
  messages: Message[];
  draft: string;
  setDraft: (value: string) => void;
  pending: boolean;
  error: string | null;
  ask: (text: string) => void;
  retry: () => void;
};

/**
 * The conversation lives above the panel so closing and reopening keeps it
 * (and an answer that arrives after closing is not lost). Reset on reload.
 */
