import {
  Ban,
  CircleCheck,
  CircleDashed,
  Clock,
  LoaderCircle,
  OctagonX,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

/** A build's state (DESIGN.md section 2, build-state colours). */
export type BuildState =
  | "succeeded"
  | "failed"
  | "unstable"
  | "running"
  | "queued"
  | "aborted"
  | "not-built";

export interface StateLook {
  word: string;
  icon: LucideIcon;
  tone: string;
}

/**
 * Each state has its own outline, so the icons differ in shape before colour. Only succeeded,
 * failed and unstable have a colour; the rest are Graphite. Running is not blue, because blue is
 * urgency in the score bar.
 */
export const BUILD_STATES: Record<BuildState, StateLook> = {
  succeeded: { word: "Succeeded", icon: CircleCheck, tone: "text-state-succeeded" },
  failed: { word: "Failed", icon: OctagonX, tone: "text-state-failed" },
  unstable: { word: "Unstable", icon: TriangleAlert, tone: "text-state-unstable" },
  running: { word: "Running", icon: LoaderCircle, tone: "text-graphite" },
  queued: { word: "Queued", icon: Clock, tone: "text-graphite" },
  aborted: { word: "Aborted", icon: Ban, tone: "text-graphite" },
  "not-built": { word: "Not built", icon: CircleDashed, tone: "text-graphite" },
};

const FROM_RESULT: Record<string, BuildState> = {
  SUCCESS: "succeeded",
  FAILURE: "failed",
  UNSTABLE: "unstable",
  ABORTED: "aborted",
  NOT_BUILT: "not-built",
  RUNNING: "running",
  BUILDING: "running",
  QUEUED: "queued",
};

/** Jenkins' result word, or the backend's, as a state. No result yet means it is still running. */
export function stateFromResult(result: string | null | undefined): BuildState {
  if (!result) {
    return "running";
  }
  return FROM_RESULT[result.toUpperCase()] ?? "not-built";
}
