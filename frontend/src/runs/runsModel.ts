/**
 * How Jobs and runs and the Overview read chains and runs (4.7.3): a chain's outcome as a build
 * state, its assistant, the filters the API does not apply itself, and what an active chain is
 * doing now.
 */

import type { ChainCard, ChainQuery, ChainSummary, Run } from "@/api/runsApi";
import { stateFromResult, type BuildState } from "@/components/buildState";
import { parseApiTime } from "@/lib/format";

/** A chain's status as a state and, where Jenkins has no word for it, the backend's. */
export function chainState(status: string): { state: BuildState; label?: string } {
  switch (status) {
    case "RUNNING":
      return { state: "running" };
    case "SUCCESS":
      return { state: "succeeded" };
    case "FAILURE":
      return { state: "failed" };
    case "ABORTED":
      return { state: "aborted" };
    // Its 30-minute lock ran out before it finished (4.6.4).
    case "EXPIRED":
      return { state: "aborted", label: "Expired" };
    default:
      return { state: stateFromResult(status) };
  }
}

export type AssistantFilter = "freestyle" | "pipeline";

/** The assistant that made a chain: freestyle chains come from one, Pipelines from the other. */
export function assistantOf(jobType: string): string {
  switch (jobType) {
    case "FREESTYLE":
      return "Freestyle";
    case "PIPELINE":
      return "Pipeline";
    default:
      return jobType;
  }
}

const JOB_TYPES = { freestyle: "FREESTYLE", pipeline: "PIPELINE" } as const satisfies Record<
  AssistantFilter,
  string
>;

export const RESULT_FILTERS = {
  running: { label: "Running", status: "RUNNING" },
  succeeded: { label: "Succeeded", status: "SUCCESS" },
  failed: { label: "Failed", status: "FAILURE" },
  aborted: { label: "Aborted", status: "ABORTED" },
  expired: { label: "Expired", status: "EXPIRED" },
} as const;

export type ResultFilter = keyof typeof RESULT_FILTERS;

export function isAssistantFilter(value: string | null): value is AssistantFilter {
  return value === "freestyle" || value === "pipeline";
}

export function isResultFilter(value: string | null): value is ResultFilter {
  return value !== null && value in RESULT_FILTERS;
}

/**
 * The page's filters as the API's own query: the backend applies all three to every chain, so a
 * filter never looks at only the newest page of them (found in T6.7).
 */
export function chainQuery({
  service,
  assistant,
  result,
}: {
  service: string | null;
  assistant: AssistantFilter | null;
  result: ResultFilter | null;
}): ChainQuery {
  return {
    ...(service ? { service } : {}),
    ...(assistant ? { jobType: JOB_TYPES[assistant] } : {}),
    ...(result ? { status: RESULT_FILTERS[result].status } : {}),
  };
}

/** How long a finished chain took, or null while it runs. */
export function chainDurationMs(chain: Pick<ChainSummary, "started_at" | "finished_at">): number | null {
  if (!chain.finished_at) {
    return null;
  }
  return Math.max(
    0,
    parseApiTime(chain.finished_at).getTime() - parseApiTime(chain.started_at).getTime(),
  );
}

/** What an active chain is doing now, in a few words: the stage or job under way. */
export function currentStep(card: ChainCard): { state: BuildState; text: string } {
  if (card.job_type === "PIPELINE") {
    const stage = card.stages.find(({ status }) => status.toUpperCase() === "IN_PROGRESS");
    if (stage) {
      return { state: "running", text: `${stage.name} stage` };
    }
  }
  const running = card.jobs.find(({ state }) => state === "running");
  if (running) {
    return { state: "running", text: running.name };
  }
  const queued = card.jobs.find(({ state }) => state === "queued");
  if (queued) {
    return { state: "queued", text: queued.name };
  }
  // Between jobs: the last one finished and the next has not been triggered yet. Naming the
  // finished job here read as if it were still running (seen in T6.9's screenshots).
  const next = card.jobs.find(({ state }) => state === "waiting" || state === "not_started");
  if (next) {
    return { state: "running", text: `Waiting to start ${next.name}` };
  }
  return { state: "running", text: card.jobs[0]?.name ?? card.service };
}

/** The newest finished runs, newest first, as the API orders them. */
export function finishedRuns(runs: readonly Run[], count: number): Run[] {
  return runs.filter(({ result }) => result !== "RUNNING").slice(0, count);
}
