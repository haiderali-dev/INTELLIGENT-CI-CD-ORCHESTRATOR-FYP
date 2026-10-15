/**
 * The backend's verdict on an edited spec, placed on the spec's own lines (4.7.1: "editable YAML
 * with inline errors").
 *
 * Check 1, "Spec schema", fails in one of two ways (backend `app/generation/validate.py`,
 * `parse_spec`):
 * - "the spec is not valid YAML: ..." with PyYAML's own "line N", or "the spec must be a YAML
 *   mapping";
 * - one or more "path: problem" parts joined by "; ", where the path is pydantic's location in
 *   the spec, such as `stages.1.template` or `version`.
 *
 * The path is found in the YAML the user is looking at. A field that is missing has no line of its
 * own, so the problem goes on the nearest thing that exists: the stage it belongs in, say.
 */

import { yamlLanguage } from "@codemirror/lang-yaml";

import type { LineDiagnostic } from "@/components/code/diagnostics";
import { lineAt } from "@/components/code/diagnostics";

import type { ValidationCheck } from "./progress";

const SPEC_CHECK = "spec_schema";

type SyntaxNode = ReturnType<typeof yamlLanguage.parser.parse>["topNode"];

function children(node: SyntaxNode, name: string): SyntaxNode[] {
  const found: SyntaxNode[] = [];
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (child.name === name) {
      found.push(child);
    }
  }
  return found;
}

/** The value of a pair or item: its first child that is not punctuation or a key. */
function valueOf(node: SyntaxNode): SyntaxNode | null {
  for (let child = node.firstChild; child; child = child.nextSibling) {
    if (child.name !== "Key" && child.name !== ":" && child.name !== "-") {
      return child;
    }
  }
  return null;
}

function unquote(text: string): string {
  return text.trim().replace(/^["']|["']$/g, "");
}

/** Where `path` is in `text`, as an offset: the deepest part of the path that exists. */
export function offsetOfPath(text: string, path: readonly (string | number)[]): number {
  const tree = yamlLanguage.parser.parse(text);
  const document = tree.topNode.getChild("Document");
  let node: SyntaxNode | null = document ? valueOf(document) : null;
  let offset = 0;
  for (const part of path) {
    if (!node) {
      break;
    }
    if (typeof part === "string" && (node.name === "BlockMapping" || node.name === "FlowMapping")) {
      const pair = children(node, "Pair").find((candidate) => {
        const key = candidate.getChild("Key");
        return key !== null && unquote(text.slice(key.from, key.to)) === part;
      });
      if (!pair) {
        break;
      }
      offset = pair.from;
      node = valueOf(pair);
    } else if (
      typeof part === "number" &&
      (node.name === "BlockSequence" || node.name === "FlowSequence")
    ) {
      const item = children(node, "Item")[part];
      if (!item) {
        break;
      }
      // An item starts with the space after its dash; its content is the line to point at.
      offset = item.from + (text.slice(item.from, item.to).length - text.slice(item.from, item.to).trimStart().length);
      node = valueOf(item);
    } else {
      break;
    }
  }
  return offset;
}

/** `stages.1.template` as the path pydantic meant: `["stages", 1, "template"]`. */
function parsePath(dotted: string): (string | number)[] {
  return dotted.split(".").map((part) => (/^\d+$/.test(part) ? Number(part) : part));
}

/** The spec schema check's problems, each on its line in `yaml`. Other checks belong to the
 * checklist, not to a line. */
export function specProblems(
  yaml: string,
  checks: readonly ValidationCheck[],
): LineDiagnostic[] {
  const check = checks.find(({ name, status }) => name === SPEC_CHECK && status === "failed");
  if (!check?.message) {
    return [];
  }
  const { message } = check;

  if (message.startsWith("the spec is not valid YAML")) {
    const lines = [...message.matchAll(/line (\d+)/g)];
    const last = lines.at(-1);
    return [{ line: last ? Number(last[1]) : null, message }];
  }
  if (message.startsWith("the spec must be")) {
    return [{ line: null, message }];
  }

  return message.split("; ").map((part) => {
    const split = part.indexOf(": ");
    if (split <= 0) {
      return { line: null, message: part };
    }
    const where = part.slice(0, split);
    const problem = part.slice(split + 2);
    if (where === "spec") {
      return { line: null, message: problem };
    }
    return { line: lineAt(yaml, offsetOfPath(yaml, parsePath(where))), message: `${where}: ${problem}` };
  });
}
