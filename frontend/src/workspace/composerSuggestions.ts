/**
 * What the composer offers while you type (4.7.4): the slash commands at the start of a message,
 * and the catalog's service names for the word under the caret.
 */

export interface Suggestion {
  value: string;
  /** What a slash command stands for. The backend rewrites them into these sentences
   * (app/services/conversations.py), so the hint is what will actually be asked. */
  hint?: string;
}

export const SLASH_COMMANDS: readonly Required<Suggestion>[] = [
  { value: "/status", hint: "Show the status of my last run" },
  { value: "/rerun", hint: "Rerun my last failed tests" },
  { value: "/help", hint: "What this assistant can do" },
];

/** The backend's limit on one message (app/api/assistants.py, MessageRequest). */
export const MESSAGE_MAX = 4000;
const MAX_SUGGESTIONS = 5;
/** Services are offered from the second letter, so a lone "p" does not open a list. */
const MIN_PREFIX = 2;

/** The word that ends at the caret, or null when the caret is inside or before a word. */
export function wordAt(text: string, caret: number): { start: number; word: string } | null {
  const after = text.charAt(caret);
  if (after !== "" && !/\s/.test(after)) {
    return null;
  }
  let start = caret;
  while (start > 0 && !/\s/.test(text.charAt(start - 1))) {
    start -= 1;
  }
  return { start, word: text.slice(start, caret) };
}

export function suggestionsFor(
  text: string,
  caret: number,
  services: readonly string[],
): Suggestion[] {
  const at = wordAt(text, caret);
  if (!at) {
    return [];
  }
  const typed = at.word.toLowerCase();
  if (at.start === 0 && typed.startsWith("/")) {
    return SLASH_COMMANDS.filter(({ value }) => value.startsWith(typed) && value !== typed);
  }
  if (typed.length < MIN_PREFIX) {
    return [];
  }
  return services
    .filter((name) => name.toLowerCase().startsWith(typed) && name.toLowerCase() !== typed)
    .slice(0, MAX_SUGGESTIONS)
    .map((value) => ({ value }));
}

/** The text with the word at the caret replaced by `value` and a space, and the caret after it. */
export function applySuggestion(
  text: string,
  caret: number,
  value: string,
): { text: string; caret: number } {
  const at = wordAt(text, caret) ?? { start: caret, word: "" };
  const before = text.slice(0, at.start);
  const after = text.slice(caret);
  const inserted = after.startsWith(" ") ? value : `${value} `;
  return { text: `${before}${inserted}${after}`, caret: before.length + inserted.length };
}
