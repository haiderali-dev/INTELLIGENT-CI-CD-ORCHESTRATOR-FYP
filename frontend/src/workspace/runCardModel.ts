/**
 * The API's run card (`RunCard`, D-058) as the run card component shows it (4.7.4): queue
 * position, score bar and waiting reason; then stage progress; then the result with its duration
 * and a link to Jenkins.
 */

import type { RunCardData } from "@/api/assistantApi";
import type { BuildState } from "@/components/buildState";

import type { RunQueue, RunStage } from "./RunCard";

type JobState = RunCardData["jobs"][number]["state"];

/** A chain job's state. "waiting" has not started: an upstream job has not finished yet. */
const JOB_STATES: Record<JobState, BuildState> = {
  success: "succeeded",
  failure: "failed",
  unstable: "unstable",
  aborted: "aborted",
  not_built: "not-built",
  running: "running",
  queued: "queued",
  waiting: "not-built",
  not_started: "not-built",
};

/** A Pipeline stage's status, in the words of Jenkins' stage view (`wfapi/describe`). */
const STAGE_STATES: Record<string, BuildState> = {
  SUCCESS: "succeeded",
  FAILED: "failed",
  UNSTABLE: "unstable",
  ABORTED: "aborted",
  NOT_EXECUTED: "not-built",
  IN_PROGRESS: "running",
  PAUSED_PENDING_INPUT: "running",
};

const CHAIN_RESULTS: Record<RunCardData["status"], BuildState | null> = {
  RUNNING: null,
  SUCCESS: "succeeded",
  FAILURE: "failed",
  ABORTED: "aborted",
  // Its 30-minute lock ran out before it finished (4.6.4).
  EXPIRED: "aborted",
};

export interface RunCardView {
  jobName: string;
  queue: RunQueue | null;
  stages: RunStage[];
  result: { state: BuildState; durationMs: number | null } | null;
  jenkinsUrl: string | null;
}

export function runCardView(card: RunCardData): RunCardView {
  const pipeline = card.job_type === "PIPELINE";
  // A Pipeline's progress is its stages; a freestyle chain's is its jobs, one per stage.
  const stages: RunStage[] = pipeline
    ? card.stages.map(({ name, status }) => ({
        name,
        state: STAGE_STATES[status.toUpperCase()] ?? "running",
      }))
    : card.jobs.map(({ name, state }) => ({ name, state: JOB_STATES[state] }));

  const resultState = CHAIN_RESULTS[card.status];
  // The run to open: the one that failed, or else the last one that ran.
  const runs = card.jobs.flatMap(({ run }) => (run ? [run] : []));
  const failed = runs.find(({ id }) => id === card.failed_run_id);
  const link = failed?.url ?? runs.at(-1)?.url ?? null;

  return {
    jobName: card.jobs[0]?.name ?? card.service,
    queue: card.queue
      ? {
          rank: card.queue.rank,
          score: card.queue.score,
          parts: card.queue.components,
          weights: card.queue.weights,
          waitingReason: card.queue.waiting_reason,
        }
      : null,
    stages,
    result: resultState ? { state: resultState, durationMs: card.duration_ms } : null,
    jenkinsUrl: link,
  };
}
