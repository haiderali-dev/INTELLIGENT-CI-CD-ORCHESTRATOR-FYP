import { Tabs } from "radix-ui";
import { lazy, Suspense, useId, useState, type ReactNode } from "react";

import { button } from "@/components/button";
import type { LineDiagnostic } from "@/components/code/diagnostics";
import { cn } from "@/lib/cn";

import { ApproveAndRun, type ApproveResult } from "./ApproveAndRun";
import { ASSISTANTS, type AssistantKind } from "./assistants";
import type { ProgressStep, ValidationCheck } from "./progress";
import { ProgressSteps, ValidationChecklist } from "./ProgressSteps";

// CodeMirror is the heaviest thing on these pages, and only the preview needs it.
const CodeView = lazy(() => import("@/components/code/CodeView"));

/** One generated artifact: a freestyle job's config.xml, or the Pipeline's Jenkinsfile. */
export interface PreviewArtifact {
  name: string;
  text: string;
  /** The same artifact before the last regenerate, to show what changed. */
  previous?: string | null;
}

export interface PreviewPlan {
  spec: {
    yaml: string;
    previous?: string | null;
    problems?: readonly LineDiagnostic[];
    onChange: (yaml: string) => void;
    /** True once the spec was edited, so it can be generated again from the edit. */
    edited: boolean;
    onRegenerate: () => void;
    regenerating?: boolean;
  };
  artifacts: readonly PreviewArtifact[];
  progress: readonly ProgressStep[];
  checks: readonly ValidationCheck[];
  explanation: { text: string | null; loading: boolean; onExplain: () => void };
  approval: { summary: string | null; ready: boolean; onApprove: () => Promise<ApproveResult> };
}

/**
 * The preview (4.7.4): the spec as editable YAML, then what it renders to (one config.xml per
 * freestyle job, or the Jenkinsfile), the checks, and the explanation, with Approve and run below
 * them. A regenerate shows its changes as a diff.
 */
export function PreviewPanel({
  assistant,
  plan,
}: {
  assistant: AssistantKind;
  /** Null until the first Generate. */
  plan: PreviewPlan | null;
}) {
  const ids = useId();
  if (!plan) {
    return (
      <p className="max-w-[68ch] px-4 pb-4 text-graphite">
        Nothing to preview yet. Ask for a build, test or deploy, then choose Generate.
      </p>
    );
  }
  const tabs = [
    { value: "spec", label: "Spec" },
    { value: "artifact", label: ASSISTANTS[assistant].artifactTab },
    { value: "checks", label: "Checks" },
    { value: "explanation", label: "Explanation" },
  ];

  return (
    <div className="flex flex-col">
      <Tabs.Root defaultValue="spec" className="flex flex-col">
        <Tabs.List aria-label="Preview" className="flex flex-wrap gap-1 border-b border-rule px-4">
          {tabs.map(({ value, label }) => (
            <Tabs.Trigger
              key={value}
              value={value}
              className="relative px-2 py-2 text-base text-graphite data-[state=active]:font-semibold data-[state=active]:text-ink data-[state=active]:after:absolute data-[state=active]:after:inset-x-2 data-[state=active]:after:-bottom-px data-[state=active]:after:h-[3px] data-[state=active]:after:bg-ink max-md:min-h-11"
            >
              {label}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        <Tabs.Content value="spec" className="flex flex-col gap-3 p-4">
          <Code>
            <CodeView
              label="Spec"
              language="yaml"
              value={plan.spec.yaml}
              previous={plan.spec.previous ?? null}
              onChange={plan.spec.onChange}
              diagnostics={plan.spec.problems ?? []}
            />
          </Code>
          {plan.spec.edited ? (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-graphite">
                You edited the spec. Generate again to check it and see what it renders.
              </p>
              <button
                type="button"
                aria-disabled={plan.spec.regenerating ?? false}
                onClick={() => {
                  if (!plan.spec.regenerating) {
                    plan.spec.onRegenerate();
                  }
                }}
                className={cn(button({ variant: "primary" }), "self-start")}
              >
                {plan.spec.regenerating ? "Generating" : "Generate from this spec"}
              </button>
            </div>
          ) : null}
        </Tabs.Content>

        <Tabs.Content value="artifact" className="p-4">
          <Artifacts assistant={assistant} artifacts={plan.artifacts} />
        </Tabs.Content>

        <Tabs.Content value="checks" className="flex flex-col gap-6 p-4">
          <section aria-labelledby={`${ids}-progress`} className="flex flex-col gap-2">
            <h3 id={`${ids}-progress`} className="font-semibold">
              Progress
            </h3>
            <ProgressSteps steps={plan.progress} />
          </section>
          <section aria-labelledby={`${ids}-checks`} className="flex flex-col gap-2">
            <h3 id={`${ids}-checks`} className="font-semibold">
              Checks
            </h3>
            <ValidationChecklist checks={plan.checks} />
          </section>
        </Tabs.Content>

        <Tabs.Content value="explanation" className="p-4">
          <Explanation {...plan.explanation} />
        </Tabs.Content>
      </Tabs.Root>

      <div className="flex flex-col gap-3 border-t border-rule p-4">
        {plan.approval.summary ? <p className="max-w-[68ch]">{plan.approval.summary}</p> : null}
        <ApproveAndRun {...plan.approval} />
      </div>
    </div>
  );
}

function Code({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<p className="text-sm text-graphite">Loading the code view</p>}>
      {children}
    </Suspense>
  );
}

function Artifacts({
  assistant,
  artifacts,
}: {
  assistant: AssistantKind;
  artifacts: readonly PreviewArtifact[];
}) {
  const [chosen, setChosen] = useState(0);
  const pickerId = useId();
  const artifact = artifacts[Math.min(chosen, artifacts.length - 1)];
  if (!artifact) {
    return <p className="text-graphite">Nothing was rendered. The checks say why.</p>;
  }
  const pipeline = assistant === "pipeline";

  return (
    <div className="flex flex-col gap-3">
      {artifacts.length > 1 ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={pickerId} className="text-sm font-semibold">
            Job
          </label>
          <select
            id={pickerId}
            value={chosen}
            onChange={(event) => {
              setChosen(Number(event.target.value));
            }}
            className="h-10 rounded-control border border-graphite bg-panel px-2 text-base max-md:h-11"
          >
            {artifacts.map(({ name }, index) => (
              <option key={name} value={index}>
                {name}
              </option>
            ))}
          </select>
        </div>
      ) : null}
      <Code>
        <CodeView
          label={pipeline ? `Jenkinsfile for ${artifact.name}` : `config.xml for ${artifact.name}`}
          language={pipeline ? "groovy" : "xml"}
          value={artifact.text}
          previous={artifact.previous ?? null}
        />
      </Code>
    </div>
  );
}

function Explanation({
  text,
  loading,
  onExplain,
}: {
  text: string | null;
  loading: boolean;
  onExplain: () => void;
}) {
  if (text) {
    // The explanation streams in; it says so until it is whole.
    return (
      <div className="flex flex-col gap-2">
        <p className="max-w-[68ch] whitespace-pre-line">{text}</p>
        {loading ? <p className="text-sm text-graphite">Still writing</p> : null}
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="max-w-[68ch] text-graphite">
        A plain-English account of what these jobs will do, written from the spec.
      </p>
      <button
        type="button"
        aria-disabled={loading}
        onClick={() => {
          if (!loading) {
            onExplain();
          }
        }}
        className={cn(button(), "self-start")}
      >
        {loading ? "Explaining" : "Explain this plan"}
      </button>
      <p aria-live="polite" className="sr-only">
        {loading ? "Writing the explanation" : ""}
      </p>
    </div>
  );
}
