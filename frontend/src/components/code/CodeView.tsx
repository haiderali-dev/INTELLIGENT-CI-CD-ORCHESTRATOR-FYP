import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { xml } from "@codemirror/lang-xml";
import { yaml } from "@codemirror/lang-yaml";
import { StreamLanguage } from "@codemirror/language";
import { groovy } from "@codemirror/legacy-modes/mode/groovy";
import { setDiagnostics, type Diagnostic } from "@codemirror/lint";
import { unifiedMergeView } from "@codemirror/merge";
import { EditorState, type Extension } from "@codemirror/state";
import { EditorView, keymap, lineNumbers } from "@codemirror/view";
import { CircleAlert } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";

import { cn } from "@/lib/cn";

import { codeHighlight, codeTheme } from "./codeTheme";
import { yamlSyntaxErrors, type LineDiagnostic } from "./diagnostics";

/** YAML for the spec, XML for a freestyle job's config.xml, Groovy for a Jenkinsfile. */
export type CodeLanguage = "yaml" | "xml" | "groovy";

function languageFor(language: CodeLanguage): Extension {
  switch (language) {
    case "yaml":
      return yaml();
    case "xml":
      return xml();
    case "groovy":
      return StreamLanguage.define(groovy);
  }
}

const NONE: readonly LineDiagnostic[] = [];

export interface CodeViewProps {
  /** The accessible name, such as "Spec" or "config.xml for fs-payment-service-build". */
  label: string;
  language: CodeLanguage;
  value: string;
  /** The text before the last regenerate. When given, the view shows what changed. */
  previous?: string | null;
  /** Makes the view editable (4.7.1: the spec YAML). Without it the code is read-only. */
  onChange?: (value: string) => void;
  /** Problems the backend found, by line. YAML syntax errors are found here as well. */
  diagnostics?: readonly LineDiagnostic[];
}

/**
 * A code view on CodeMirror 6 (4.7.1). Read-only code can still be focused, selected and scrolled
 * from the keyboard. Tab is left to move focus, so the editor never traps it. Long lines scroll
 * inside the view rather than the page (DESIGN.md section 8, 360 px).
 */
export default function CodeView({
  label,
  language,
  value,
  previous = null,
  onChange,
  diagnostics = NONE,
}: CodeViewProps) {
  const editable = onChange !== undefined;
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);

  const problems = useMemo(() => {
    if (!editable) {
      return NONE;
    }
    const found = language === "yaml" ? yamlSyntaxErrors(value) : [];
    const lines = new Set(found.map(({ line }) => line));
    // Problems about the whole text come first, then by line.
    return [...found, ...diagnostics.filter(({ line }) => line === null || !lines.has(line))].sort(
      (a, b) => (a.line ?? 0) - (b.line ?? 0),
    );
  }, [editable, language, value, diagnostics]);

  const latest = useRef({ value, onChange, problems });
  useEffect(() => {
    latest.current = { value, onChange, problems };
  });

  // The editor is rebuilt only when what it is changes; new text is dispatched into it below.
  useEffect(() => {
    const parent = host.current;
    if (!parent) {
      return undefined;
    }
    const editor = new EditorView({
      parent,
      state: EditorState.create({
        doc: latest.current.value,
        extensions: [
          lineNumbers(),
          languageFor(language),
          codeHighlight,
          codeTheme,
          EditorView.contentAttributes.of({ "aria-label": label }),
          editable
            ? [
                history(),
                keymap.of([...defaultKeymap, ...historyKeymap]),
                EditorView.updateListener.of((update) => {
                  if (update.docChanged) {
                    latest.current.onChange?.(update.state.doc.toString());
                  }
                }),
              ]
            : [
                EditorState.readOnly.of(true),
                EditorView.editable.of(false),
                EditorView.contentAttributes.of({ tabindex: "0", "aria-readonly": "true" }),
              ],
          previous === null
            ? []
            : unifiedMergeView({
                original: previous,
                mergeControls: false,
                gutter: true,
                highlightChanges: true,
                syntaxHighlightDeletions: true,
              }),
        ],
      }),
    });
    view.current = editor;
    showProblems(editor, latest.current.problems);
    return () => {
      editor.destroy();
      view.current = null;
    };
  }, [label, language, editable, previous]);

  useEffect(() => {
    const editor = view.current;
    if (!editor) {
      return;
    }
    const current = editor.state.doc.toString();
    if (current !== value) {
      editor.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    const editor = view.current;
    if (editor && editable) {
      showProblems(editor, problems);
    }
  }, [editable, problems]);

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div
        ref={host}
        className={cn("min-w-0 overflow-hidden border", editable ? "border-graphite" : "border-rule")}
      />
      {problems.length > 0 ? (
        <ul aria-label={`Problems in ${label}`} className="flex flex-col gap-1 text-sm">
          {problems.map(({ line, message }) => (
            <li key={`${line} ${message}`} className="flex items-start gap-1.5">
              <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
              <span>
                <span className="font-semibold">{line === null ? "Spec" : `Line ${line}`}</span>{" "}
                {message}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Underlines each problem's line in the editor, with its words in a tooltip. A problem with no
 * line is only listed. */
function showProblems(editor: EditorView, problems: readonly LineDiagnostic[]): void {
  const { doc } = editor.state;
  const marks: Diagnostic[] = problems.flatMap(({ line, message }) => {
    if (line === null) {
      return [];
    }
    const at = doc.line(Math.min(Math.max(line, 1), doc.lines));
    return [{ from: at.from, to: at.to, severity: "error" as const, message }];
  });
  editor.dispatch(setDiagnostics(editor.state, marks));
}
