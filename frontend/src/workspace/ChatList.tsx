import { Plus } from "lucide-react";

import type { components } from "@/api/schema";
import { button } from "@/components/button";
import { cn } from "@/lib/cn";

type Conversation = components["schemas"]["ConversationResponse"];

const WHEN = new Intl.DateTimeFormat(undefined, {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/** This assistant's chats, newest first as the API sends them, and the way to start another. */
export function ChatList({
  chats,
  activeId,
  onSelect,
  onNew,
}: {
  chats: readonly Conversation[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="flex flex-col gap-2 pb-4">
      {chats.length === 0 ? (
        <p className="px-4 text-sm text-graphite">No chats yet. Your first message starts one.</p>
      ) : (
        <ul className="flex flex-col">
          {chats.map(({ id, title, created_at: createdAt }) => {
            const active = id === activeId;
            return (
              <li key={id}>
                <button
                  type="button"
                  aria-current={active ? "true" : undefined}
                  onClick={() => {
                    onSelect(id);
                  }}
                  className={cn(
                    "relative flex w-full flex-col px-4 py-2 text-left hover:bg-ground max-md:min-h-11",
                    active &&
                      "bg-ground font-semibold before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:bg-ink",
                  )}
                >
                  <span className="truncate text-sm">{title}</span>
                  <span className="text-sm font-normal text-graphite tabular-nums">
                    {WHEN.format(new Date(createdAt))}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="px-4 pt-2">
        <button type="button" onClick={onNew} className={cn(button(), "w-full")}>
          <Plus aria-hidden="true" className="size-4" />
          New chat
        </button>
      </div>
    </div>
  );
}
