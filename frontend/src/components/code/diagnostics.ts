import { yamlLanguage } from "@codemirror/lang-yaml";

/** A problem on one line, 1-based, as the spec editor shows it inline and in its list. */
export interface LineDiagnostic {
  line: number;
  message: string;
}

export const YAML_SYNTAX_MESSAGE =
  "This line is not valid YAML. Check its indentation, colons and quotes.";

/**
 * Lines where YAML's structure breaks, found by the same parser that colours the editor, so the
 * commonest mistakes show before anything is sent: a line indented under a plain value, an
 * unclosed bracket or brace, a stray closing one, a dash out of line. One entry per line.
 *
 * It is a highlighting grammar, not a validator: an unterminated quote or a tab parses without
 * complaint (checked 2026-10-15). The backend's check 1 (`parse_spec`) is the authority, and its
 * problems arrive as `diagnostics`.
 */
export function yamlSyntaxErrors(text: string): LineDiagnostic[] {
  const tree = yamlLanguage.parser.parse(text);
  // An unclosed bracket is noticed where the text runs out, which is often a blank last line; it
  // is reported on the last line with something on it instead.
  const lastContent = Math.max(text.trimEnd().length - 1, 0);
  const lines = new Set<number>();
  tree.iterate({
    enter(node) {
      if (node.type.isError) {
        lines.add(lineAt(text, Math.min(node.from, lastContent)));
      }
    },
  });
  return [...lines].sort((a, b) => a - b).map((line) => ({ line, message: YAML_SYNTAX_MESSAGE }));
}

/** The 1-based line holding character `offset`. */
export function lineAt(text: string, offset: number): number {
  let line = 1;
  for (let index = 0; index < Math.min(offset, text.length); index += 1) {
    if (text[index] === "\n") {
      line += 1;
    }
  }
  return line;
}
