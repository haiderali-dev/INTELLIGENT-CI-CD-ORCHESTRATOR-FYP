import { Link2, Workflow, type LucideIcon } from "lucide-react";

import type { Accent } from "@/app/shell/nav";

export type AssistantKind = "freestyle" | "pipeline";

export interface AssistantIdentity {
  kind: AssistantKind;
  name: string;
  /** Spruce for Freestyle, Plum for Pipeline: identity only, never a button or a chart. */
  accent: Accent;
  /** Freestyle's chain glyph, Pipeline's stage-track glyph (DESIGN.md principle 5). */
  icon: LucideIcon;
  /** The page header's sentence. */
  description: string;
  /** The empty state's one sentence on what this assistant creates (4.7.4). */
  creates: string;
  /** Four commands to click, from 4.6.5's list of commands version 1 must handle. */
  examples: readonly [string, string, string, string];
  /** Each assistant's own composer placeholder, so the two are never confused. */
  placeholder: string;
  /** What the preview shows (4.6): one config.xml per job, or the Jenkinsfile. */
  artifactTab: "Config" | "Jenkinsfile";
}

export const ASSISTANTS: Record<AssistantKind, AssistantIdentity> = {
  freestyle: {
    kind: "freestyle",
    name: "Freestyle Assistant",
    accent: "spruce",
    icon: Link2,
    description: "Creates chained freestyle jobs on staging, from plain English.",
    creates:
      "Creates a chain of freestyle jobs on staging, each started when the one before it succeeds: build, then test, then deploy.",
    examples: [
      "Build payment-service from main",
      "Run the integration tests for payment-service on feature/refund",
      "Deploy auth-service to staging, high priority, hotfix for login bug",
      "What's the status of my last deploy?",
    ],
    placeholder: "Message the Freestyle Assistant",
    artifactTab: "Config",
  },
  pipeline: {
    kind: "pipeline",
    name: "Pipeline Assistant",
    accent: "plum",
    icon: Workflow,
    description: "Creates Pipeline jobs on staging, from plain English.",
    creates:
      "Creates one Pipeline job on staging, whose stages run in order in a single run, from a declarative Jenkinsfile.",
    examples: [
      "Build, test and deploy the latest commit of payment-service to staging",
      "Build payment-service from main",
      "Deploy auth-service to staging, high priority, hotfix for login bug",
      "Rerun the failed payment-service tests",
    ],
    placeholder: "Message the Pipeline Assistant",
    artifactTab: "Jenkinsfile",
  },
};
