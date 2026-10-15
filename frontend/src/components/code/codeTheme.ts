/**
 * How code views look. They wear the page's colours and nothing else (DESIGN.md section 2): Ink,
 * Graphite and mixes of them into Panel, in IBM Plex Mono, which section 3 keeps for code.
 *
 * CodeMirror's own defaults draw errors in red and diffs in red and green, which DESIGN.md
 * reserves for build states. Here an error is an Ink wavy underline with its words beside it, an
 * insertion is a tint of Ink with an Ink gutter mark, and a deletion is struck through in Graphite.
 * The selectors match the specificity of the package defaults they replace, and themes outrank base
 * themes, so these win in both modes.
 */

import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags } from "@lezer/highlight";

const tint = (colour: string, percent: number) =>
  `color-mix(in oklab, var(--${colour}) ${percent}%, var(--panel))`;
const underline = (colour: string) =>
  `linear-gradient(var(--${colour}), var(--${colour})) bottom / 100% 2px no-repeat`;

export const codeTheme = EditorView.theme({
  // The border is the host's: Graphite when the code can be edited, since it is then a control,
  // and Rule when it is only read (section 7).
  "&": {
    color: "var(--ink)",
    backgroundColor: "var(--panel)",
    fontSize: "0.875rem",
  },
  // Section 8: a 2px Ink outline with a 2px offset, never removed.
  "&.cm-focused": { outline: "2px solid var(--ink)", outlineOffset: "2px" },
  ".cm-scroller": {
    fontFamily: '"IBM Plex Mono", ui-monospace, monospace',
    lineHeight: "1.5rem",
  },
  ".cm-content": { caretColor: "var(--ink)", padding: "0.5rem 0" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--ink)" },
  "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: tint("graphite", 30),
  },
  ".cm-gutters": {
    backgroundColor: "var(--panel)",
    color: "var(--graphite)",
    borderRight: "1px solid var(--rule)",
  },
  ".cm-activeLine, .cm-activeLineGutter": { backgroundColor: "transparent" },

  // Inline errors (4.7.1: "editable YAML with inline errors").
  "& .cm-lintRange-error": {
    backgroundImage: "none",
    textDecoration: "underline wavy var(--ink)",
    textUnderlineOffset: "3px",
  },
  "& .cm-lintRange-warning": {
    backgroundImage: "none",
    textDecoration: "underline wavy var(--graphite)",
    textUnderlineOffset: "3px",
  },
  "& .cm-diagnostic-error": { borderLeft: "4px solid var(--ink)" },
  "& .cm-diagnostic-warning": { borderLeft: "4px solid var(--graphite)" },
  "& .cm-tooltip": {
    backgroundColor: "var(--panel)",
    color: "var(--ink)",
    border: "1px solid var(--rule)",
    borderRadius: "8px",
  },

  // The diff shown after a regenerate.
  "&.cm-merge-b .cm-changedLine, & .cm-inlineChangedLine": {
    backgroundColor: tint("ink", 7),
  },
  "& .cm-deletedChunk": { backgroundColor: tint("graphite", 14), color: "var(--graphite)" },
  "&.cm-merge-b .cm-changedText": { background: underline("ink") },
  "& .cm-deletedChunk .cm-deletedText, &.cm-merge-b .cm-deletedText": {
    background: "none",
    textDecoration: "line-through",
  },
  "& .cm-deletedLine, & .cm-deletedLine del": { textDecoration: "line-through" },
  "&.cm-merge-b .cm-changedLineGutter, & .cm-inlineChangedLineGutter": {
    background: "var(--ink)",
  },
  "& .cm-deletedLineGutter": { background: "var(--graphite)" },
});

/** Syntax is told apart by weight and Graphite, not by hue. */
export const codeHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: [tags.keyword, tags.definitionKeyword, tags.modifier], fontWeight: "600" },
    { tag: [tags.propertyName, tags.tagName, tags.attributeName], fontWeight: "600" },
    { tag: [tags.string, tags.special(tags.string), tags.attributeValue], color: "var(--graphite)" },
    {
      tag: [tags.comment, tags.lineComment, tags.blockComment],
      color: "var(--graphite)",
      fontStyle: "italic",
    },
    { tag: [tags.punctuation, tags.bracket, tags.angleBracket], color: "var(--graphite)" },
    { tag: tags.invalid, textDecoration: "underline wavy var(--ink)" },
  ]),
);
