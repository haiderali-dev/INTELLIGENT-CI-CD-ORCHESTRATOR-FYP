import { Children, useEffect, useRef, type ReactNode } from "react";

import { ACCENT_TEXT } from "@/app/shell/nav";
import { cn } from "@/lib/cn";

import { ASSISTANTS, type AssistantKind } from "./assistants";

/**
 * The conversation, oldest first. It is `aria-live="polite"`, so each new message is announced
 * once (DESIGN.md section 8), and it scrolls to the newest message when one arrives.
 */
export function Thread({ label, children }: { label: string; children: ReactNode }) {
  const end = useRef<HTMLDivElement>(null);
  const count = Children.count(children);

  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [count]);

  return (
    <div className="flex flex-col">
      <ol aria-label={label} aria-live="polite" className="flex flex-col gap-6">
        {children}
      </ol>
      <div ref={end} />
    </div>
  );
}

/**
 * One message. Messages are not boxed (DESIGN.md section 9): a name line, then the words, then any
 * card that belongs to them. The assistant's name carries its glyph in its colour.
 */
export function ThreadMessage({
  author,
  assistant,
  children,
}: {
  author: "user" | "assistant";
  assistant: AssistantKind;
  children: ReactNode;
}) {
  const { name, icon: Icon, accent } = ASSISTANTS[assistant];
  return (
    <li className="animate-[message-in_120ms_ease-out]">
      <p className="flex items-center gap-1.5 text-sm font-semibold">
        {author === "user" ? (
          "You"
        ) : (
          <>
            <Icon aria-hidden="true" className={cn("size-4", ACCENT_TEXT[accent])} />
            {name}
          </>
        )}
      </p>
      <div className="mt-1 flex max-w-[68ch] flex-col gap-3 text-base">{children}</div>
    </li>
  );
}

/** A message's words, keeping the line breaks a help card is written with. */
export function MessageText({ children }: { children: string }) {
  return <p className="whitespace-pre-line">{children}</p>;
}
