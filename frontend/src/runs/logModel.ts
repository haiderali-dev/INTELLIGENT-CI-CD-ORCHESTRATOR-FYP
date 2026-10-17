/**
 * The end of a log. The API reads a run's console output in windows from a byte offset; the page
 * keeps reading to the end and shows only the last lines, because that is where a build says how
 * it ended.
 */

export const TAIL_LINES = 200;

/** How many lines `text` adds to a log: a line counts once its newline has arrived. */
export function countLines(text: string): number {
  let count = 0;
  for (const character of text) {
    if (character === "\n") {
      count += 1;
    }
  }
  return count;
}

/**
 * The end of `text` from the start of its last `lines` lines, newlines intact, so the next window
 * of the log can be appended to it. An unfinished last line counts as one.
 */
export function keepEnd(text: string, lines: number): string {
  let seen = 0;
  // A trailing newline ends the last line; it does not start another.
  for (let index = text.endsWith("\n") ? text.length - 2 : text.length - 1; index >= 0; index -= 1) {
    if (text[index] === "\n") {
      seen += 1;
      if (seen === lines) {
        return text.slice(index + 1);
      }
    }
  }
  return text;
}

/** The last `lines` lines of `text` for display, with an unfinished last line kept. */
export function lastLines(text: string, lines: number = TAIL_LINES): string {
  const parts = text.split("\n");
  // A trailing newline ends the last line rather than starting an empty one.
  const complete = text.endsWith("\n") ? parts.slice(0, -1) : parts;
  return complete.slice(-lines).join("\n");
}
