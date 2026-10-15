import type { Message } from "@/api/assistantApi";

/**
 * The thread's order: oldest first, and at the same moment the user's message before the reply.
 *
 * The backend orders by `created_at`, then by id. A message and its reply are written in one
 * request, and a clock with coarse resolution (Windows', for one) can stamp both with the same
 * time. The ids are random, so the reply could come first. A reply always answers the message
 * before it, so on a tie the user's goes first.
 */
export function inThreadOrder(messages: readonly Message[]): Message[] {
  return messages
    .map((message, index) => ({ message, index }))
    .sort((a, b) => {
      const byTime = Date.parse(a.message.created_at) - Date.parse(b.message.created_at);
      if (byTime !== 0) {
        return byTime;
      }
      const byRole = roleRank(a.message) - roleRank(b.message);
      return byRole !== 0 ? byRole : a.index - b.index;
    })
    .map(({ message }) => message);
}

function roleRank(message: Message): number {
  return message.role === "USER" ? 0 : 1;
}
