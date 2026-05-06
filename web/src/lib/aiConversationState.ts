import type { ChatMessage } from "@/api";

/** Minimum shape needed by `mergeLoadedAIConversation` / `setAIReplyTarget`.
 * Callers may extend this with extra fields (e.g. Dashboard's `slow`,
 * `errorDetail`, `lastSendArgs`); the helpers preserve those via the
 * generic `T extends AIConversationThreadState<...>`. */
export type AIConversationThreadState<TMessage extends ChatMessage> = {
  loaded: boolean;
  loading: boolean;
  messages: TMessage[];
  replyTarget: string | null;
  input: string;
  streaming: boolean;
  nextId: number;
};

export type LoadedAIConversation = {
  messages: ChatMessage[];
  reply_target: string | null;
};

export function mergeLoadedAIConversation<
  TMessage extends ChatMessage,
  T extends AIConversationThreadState<TMessage>,
>(
  existing: T,
  conversation: LoadedAIConversation,
): T {
  const mapped = conversation.messages.map((m, idx) => ({
    ...m,
    id: idx + 1,
  })) as unknown as TMessage[];

  return {
    ...existing,
    loaded: true,
    loading: false,
    messages: mapped,
    replyTarget: existing.replyTarget ?? conversation.reply_target,
    nextId: mapped.length + 1,
  };
}

export function setAIReplyTarget<
  TMessage extends ChatMessage,
  T extends AIConversationThreadState<TMessage>,
>(
  existing: T,
  replyTarget: string | null,
): {
  state: T;
  changed: boolean;
} {
  if (existing.replyTarget === replyTarget) {
    return { state: existing, changed: false };
  }

  return {
    state: {
      ...existing,
      replyTarget,
    },
    changed: true,
  };
}
