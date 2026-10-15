import { useMemo } from "react";

import CodeView from "@/components/code/CodeView";

import type { ValidationCheck } from "./progress";
import { specProblems } from "./specProblems";

/**
 * The editable spec, with the backend's verdict on its lines (4.7.1). Loaded lazily with the code
 * views: placing a problem needs the YAML parser, which belongs to CodeMirror's chunk, not to every
 * page's.
 */
export default function SpecEditor({
  yaml,
  previous,
  checks,
  onChange,
}: {
  yaml: string;
  previous: string | null;
  checks: readonly ValidationCheck[];
  onChange: (yaml: string) => void;
}) {
  const problems = useMemo(() => specProblems(yaml, checks), [yaml, checks]);
  return (
    <CodeView
      label="Spec"
      language="yaml"
      value={yaml}
      previous={previous}
      onChange={onChange}
      diagnostics={problems}
    />
  );
}
