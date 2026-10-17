/**
 * How the Queue page reads the plugin's ranking (DESIGN.md section 4, Queue): the job type in words,
 * the estimate and the wait as durations, and the upstream jobs a job names that do not exist.
 */

import type { Queue, QueueItem } from "@/api/queueApi";
import { formatDuration } from "@/lib/format";

/** The plugin reports each job's Jenkins class (`DynamicQueueApi.renderItem`), or "unknown". */
const JOB_TYPES: Readonly<Record<string, string>> = {
  FreeStyleProject: "Freestyle",
  WorkflowJob: "Pipeline",
  MavenModuleSet: "Maven",
  unknown: "Unknown",
};

export function jobTypeLabel(jobType: string): string {
  return JOB_TYPES[jobType] ?? jobType;
}

/** The plugin's estimate from build history, or why there is none. */
export function formatEstimate(seconds: number | null): string {
  if (seconds === null) {
    return "No history";
  }
  // formatDuration rounds to whole seconds, and a 0.2 s build is not a 0 s one.
  if (seconds < 0.5) {
    return "Under 1s";
  }
  return formatDuration(seconds * 1000);
}

/**
 * How long an item has waited: seconds for the first minute, then whole minutes ("6m", "17m"), then
 * hours and minutes. Aging moves in five-minute steps, so seconds past the first minute are noise.
 */
export function formatWait(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  if (total < 60) {
    return `${total}s`;
  }
  const minutes = Math.floor(total / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/**
 * The upstream jobs this job says it depends on that Jenkins does not have. The plugin reports them
 * and never waits on them (`DependencyGate.unresolvedUpstream`), so they are a mistake in the job's
 * configuration, not a reason it is waiting.
 */
export function missingUpstreamNote(item: QueueItem): string | null {
  const names = item.unresolved_dependencies;
  if (names.length === 0) {
    return null;
  }
  return `${names.length === 1 ? "Upstream job not found" : "Upstream jobs not found"}: ${names.join(", ")}`;
}

/** Highest score first, in the plugin's own rank order. */
export function ranked(queue: Queue): QueueItem[] {
  return [...queue.items].sort((a, b) => a.rank - b.rank);
}

/** What the header says about the optimizer; nothing when the plugin could not be read. */
export function optimizerStatus(queue: Queue): string | null {
  if (!queue.available) {
    return null;
  }
  return queue.optimizer_enabled ? "Optimizer on" : "Optimizer off: Jenkins' own order";
}
