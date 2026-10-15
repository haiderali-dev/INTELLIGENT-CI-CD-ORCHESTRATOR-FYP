import { Send, Square } from "lucide-react";
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";

import { button } from "@/components/button";
import { cn } from "@/lib/cn";

import { ASSISTANTS, type AssistantKind } from "./assistants";
import {
  applySuggestion,
  MESSAGE_MAX,
  suggestionsFor,
  type Suggestion,
} from "./composerSuggestions";

/** Below this many characters left, the composer says how many remain. */
const NEARLY_FULL = 200;

/**
 * The composer (4.7.4). Enter sends and Shift+Enter adds a line. /status, /rerun and /help are
 * offered at the start of a message and service names as you type them: arrow keys move through
 * the list, Enter or Tab takes one, Escape closes it. While the assistant is answering, a Stop
 * button takes Send's place and typing still works.
 *
 * Controlled: the page owns the draft, so an example command can fill it and a chat can keep its
 * own. The list is tied to the text box with aria-activedescendant, and its size is announced.
 */
export function Composer({
  assistant,
  value,
  onChange,
  onSend,
  waiting,
  onStop,
  services,
}: {
  assistant: AssistantKind;
  value: string;
  onChange: (value: string) => void;
  onSend: (text: string) => void;
  /** True while the assistant is answering. */
  waiting: boolean;
  onStop: () => void;
  services: readonly string[];
}) {
  const { placeholder } = ASSISTANTS[assistant];
  const ids = useId();
  const listId = `${ids}-suggestions`;
  const box = useRef<HTMLTextAreaElement>(null);
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  // Escape closes the list until the text changes again.
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);
  const pendingCaret = useRef<number | null>(null);

  const suggestions: Suggestion[] =
    dismissedFor === value ? [] : suggestionsFor(value, caret, services);
  const open = suggestions.length > 0;
  const activeIndex = Math.min(active, Math.max(suggestions.length - 1, 0));
  const left = MESSAGE_MAX - value.length;

  useLayoutEffect(() => {
    if (pendingCaret.current !== null && box.current) {
      box.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
      pendingCaret.current = null;
    }
  }, [value]);

  const update = (text: string, at: number) => {
    setCaret(at);
    setActive(0);
    onChange(text);
  };

  const accept = (suggestion: Suggestion) => {
    const next = applySuggestion(value, caret, suggestion.value);
    pendingCaret.current = next.caret;
    update(next.text, next.caret);
  };

  const send = () => {
    const text = value.trim();
    if (!waiting && text) {
      onSend(text);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) {
      return;
    }
    if (open) {
      const chosen = suggestions[activeIndex];
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setActive((activeIndex + step + suggestions.length) % suggestions.length);
        return;
      }
      if ((event.key === "Enter" || event.key === "Tab") && !event.shiftKey && chosen) {
        event.preventDefault();
        accept(chosen);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setDismissedFor(value);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  };

  return (
    <form
      aria-label="Message"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
      className="flex flex-col gap-1"
    >
      <div className="relative flex items-end gap-2">
        {open ? (
          <ul
            id={listId}
            role="listbox"
            aria-label="Suggestions"
            className="absolute right-0 bottom-full left-0 z-30 mb-2 flex max-h-60 flex-col overflow-y-auto rounded-float bg-panel py-1 shadow-float dark:border dark:border-rule"
          >
            {suggestions.map((suggestion, index) => (
              <li
                key={suggestion.value}
                id={`${listId}-${String(index)}`}
                role="option"
                aria-selected={index === activeIndex}
                // Mouse down, not click, so the text box keeps focus.
                onMouseDown={(event) => {
                  event.preventDefault();
                  accept(suggestion);
                }}
                className={cn(
                  "flex cursor-pointer flex-wrap items-baseline gap-x-2 px-3 py-2 max-md:min-h-11",
                  index === activeIndex && "bg-ground font-semibold",
                )}
              >
                <span>{suggestion.value}</span>
                {suggestion.hint ? (
                  <span className="text-sm font-normal text-graphite">{suggestion.hint}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}

        <label htmlFor={`${ids}-text`} className="sr-only">
          {placeholder}
        </label>
        <textarea
          ref={box}
          id={`${ids}-text`}
          value={value}
          rows={2}
          maxLength={MESSAGE_MAX}
          placeholder={placeholder}
          aria-autocomplete="list"
          aria-controls={open ? listId : undefined}
          aria-activedescendant={open ? `${listId}-${String(activeIndex)}` : undefined}
          aria-describedby={`${ids}-hint`}
          onChange={(event) => {
            update(event.target.value, event.target.selectionStart);
          }}
          onSelect={(event) => {
            setCaret(event.currentTarget.selectionStart);
          }}
          onKeyDown={onKeyDown}
          className="max-h-48 min-h-11 flex-1 resize-none rounded-control border border-graphite bg-panel px-3 py-2 text-base text-ink placeholder:text-graphite"
        />

        {waiting ? (
          <button type="button" onClick={onStop} className={button()}>
            <Square aria-hidden="true" className="size-4" />
            Stop
          </button>
        ) : (
          <button
            type="submit"
            aria-disabled={value.trim() === ""}
            className={button({ variant: "primary" })}
          >
            <Send aria-hidden="true" className="size-4" />
            Send
          </button>
        )}
      </div>

      <p id={`${ids}-hint`} className="flex flex-wrap items-baseline justify-between gap-x-4 text-graphite">
        {/* text-xs is for keyboard hints and axis ticks only (DESIGN.md section 3). */}
        <span className="text-xs max-md:sr-only">Enter sends. Shift+Enter adds a line.</span>
        {left <= NEARLY_FULL ? (
          <span className="text-sm tabular-nums">{`${String(left)} characters left`}</span>
        ) : null}
      </p>
      <p aria-live="polite" className="sr-only">
        {open
          ? `${String(suggestions.length)} ${suggestions.length === 1 ? "suggestion" : "suggestions"}. Up and down arrows choose, Enter takes one.`
          : ""}
      </p>
    </form>
  );
}
