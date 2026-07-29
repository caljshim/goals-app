import type { ChatMessage } from "./types";

export type CopilotMessage = ChatMessage & {
  id: string;
  actions?: string[];
};

export function branchConversation(
  messages: CopilotMessage[],
  messageId: string,
  replacement: string | undefined,
  nextId: string,
): CopilotMessage[] | null {
  const index = messages.findIndex((message) => message.id === messageId);
  const source = messages[index];
  if (!source || source.role !== "user") return null;

  const content = (replacement ?? source.content).trim();
  if (!content) return null;

  return [
    ...messages.slice(0, index),
    {
      id: nextId,
      role: "user",
      content,
      ...(source.attachment_ids?.length
        ? { attachment_ids: source.attachment_ids }
        : {}),
    },
  ];
}
