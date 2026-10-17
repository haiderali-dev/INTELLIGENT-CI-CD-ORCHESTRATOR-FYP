import { ChevronUp, MessagesSquare, PanelRight } from "lucide-react";
import { useState, type ReactNode } from "react";

import { button } from "@/components/button";
import { PageHeader } from "@/components/PageHeader";
import { Sheet } from "@/components/Sheet";
import { cn } from "@/lib/cn";
import { MEDIUM_QUERY, useMediaQuery, WIDE_QUERY } from "@/lib/useMediaQuery";

import { ASSISTANTS, type AssistantKind } from "./assistants";

/**
 * The assistant workspace (4.7.4, DESIGN.md section 4): chats, thread and preview side by side, so
 * the conversation and the exact jobs it will create are visible together. Under 1280 px the
 * preview becomes a drawer and the chats a sheet; under 768 px the preview is a bottom sheet whose
 * handle says, in one line, what it holds.
 *
 * Each region is rendered in exactly one place at a time, so nothing is announced twice. Whatever
 * must survive a drawer closing, such as an edited spec, belongs to the page, not to the preview.
 */
export function WorkspaceLayout({
  assistant,
  activeChatId,
  chats,
  thread,
  composer,
  preview,
  previewSummary,
}: {
  assistant: AssistantKind;
  /** Choosing another chat closes the chats sheet. */
  activeChatId: string | null;
  chats: ReactNode;
  thread: ReactNode;
  composer: ReactNode;
  preview: ReactNode;
  /** One line for the bottom sheet's handle, such as "Preview: 3 jobs, all checks pass". */
  previewSummary: string;
}) {
  const wide = useMediaQuery(WIDE_QUERY, true);
  const medium = useMediaQuery(MEDIUM_QUERY, true);
  const { name, description, accent } = ASSISTANTS[assistant];

  // The sheet is open for the chat that was active when it opened, so picking another one (or
  // starting a new one) closes it without an effect.
  const [chatsOpenFor, setChatsOpenFor] = useState<string | null | undefined>(undefined);
  const chatsOpen = chatsOpenFor !== undefined && chatsOpenFor === activeChatId;
  const [previewOpen, setPreviewOpen] = useState(false);

  return (
    <div className="flex flex-col md:h-dvh">
      <PageHeader title={name} description={description} accent={accent} />

      <div
        className={cn(
          "flex min-h-0 flex-1",
          // At 1280 px, beside the shell's 240 px sidebar, the thread keeps 416 px.
          wide ? "grid grid-cols-[13rem_minmax(0,1fr)_26rem]" : "flex-col",
        )}
      >
        {wide ? (
          <aside aria-labelledby="chats-heading" className="min-h-0 overflow-y-auto border-r border-rule">
            <h2 id="chats-heading" className="px-4 pt-4 pb-2 text-lg font-semibold">
              Chats
            </h2>
            {chats}
          </aside>
        ) : null}

        <section aria-label="Conversation" className="flex min-h-0 min-w-0 flex-1 flex-col">
          {wide ? null : (
            <div className="flex flex-wrap items-center gap-2 border-b border-rule px-4 py-2">
              <Sheet
                side="left"
                title="Chats"
                open={chatsOpen}
                onOpenChange={(open) => {
                  setChatsOpenFor(open ? activeChatId : undefined);
                }}
                trigger={
                  <button type="button" className={button()}>
                    <MessagesSquare aria-hidden="true" className="size-4" />
                    Chats
                  </button>
                }
              >
                {chats}
              </Sheet>
              {medium ? (
                <Sheet
                  side="right"
                  title="Preview"
                  open={previewOpen}
                  onOpenChange={setPreviewOpen}
                  trigger={
                    <button type="button" className={button()}>
                      <PanelRight aria-hidden="true" className="size-4" />
                      Preview
                    </button>
                  }
                >
                  {preview}
                </Sheet>
              ) : null}
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-6">{thread}</div>

          <div className="sticky bottom-0 flex flex-col gap-2 border-t border-rule bg-panel px-4 py-3 md:static md:px-6">
            {medium ? null : (
              <Sheet
                side="bottom"
                title="Preview"
                open={previewOpen}
                onOpenChange={setPreviewOpen}
                trigger={
                  <button
                    type="button"
                    className="flex min-h-11 w-full items-center justify-between gap-2 rounded-control border border-graphite px-3 text-left text-sm"
                  >
                    <span>{previewSummary}</span>
                    <ChevronUp aria-hidden="true" className="size-4 shrink-0" />
                  </button>
                }
              >
                {preview}
              </Sheet>
            )}
            {composer}
          </div>
        </section>

        {wide ? (
          <aside
            aria-labelledby="preview-heading"
            className="min-h-0 overflow-y-auto border-l border-rule"
          >
            <h2 id="preview-heading" className="px-4 pt-4 pb-2 text-lg font-semibold">
              Preview
            </h2>
            {preview}
          </aside>
        ) : null}
      </div>
    </div>
  );
}
