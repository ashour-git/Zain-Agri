import { apiRequest } from "@/lib/api";

export type ChatTurn = { role: "user" | "assistant"; content: string };
export type ChatSource = { tool: string; label: string };
export type ChatReply = { reply: string; sources: ChatSource[]; remaining_today: number };
export type AssistantStatus = { enabled: boolean; remaining_today: number };

/** Turns sent per question; the server trims further by size. */
export const HISTORY_TURNS = 10;
export const MAX_QUESTION_CHARS = 500;

export function getAssistantStatus(): Promise<AssistantStatus> {
  return apiRequest<AssistantStatus>("/api/v1/assistant/status");
}

export function askAssistant(messages: ChatTurn[]): Promise<ChatReply> {
  return apiRequest<ChatReply>("/api/v1/assistant/chat", {
    method: "POST",
    body: { messages: messages.slice(-HISTORY_TURNS) },
  });
}
