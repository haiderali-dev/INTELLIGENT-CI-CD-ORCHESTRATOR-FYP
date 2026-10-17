import { ExternalLink } from "lucide-react";

import { BUILD_STATES, type BuildState } from "@/components/buildState";
import { BuildStateLabel } from "@/components/BuildStateLabel";
import { ScoreBar } from "@/components/ScoreBar";
import type { ScoreComponents, ScoreWeights } from "@/components/scoreBarModel";
import { formatDuration, ordinal } from "@/lib/format";

/** Where the run waits, as the plugin ranks it. */
export interface RunQueue {
  rank: number;
  score: number;
  parts: ScoreComponents;
  weights: ScoreWeights;
  /** The plugin's blocked reason, when it has one. */
  waitingReason: string | null;
}

export interface RunStage {
  name: string;
  state: BuildState;
}

const WAITING = "Waiting for a free executor";

/** A link out must be a web address, never a script. */
function isWebAddress(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

/**
 * The run card (4.7.4): queue position, score bar and waiting reason; then stage progress; then the
 * result with its duration and a link to Jenkins. A Rule-bordered block with no shadow, unlike
 * the intent card in content and height (DESIGN.md section 9). When the plugin cannot be read, it
 * says so, never an empty bar (section 6).
 */
export function RunCard({
  jobName,
  queue = null,
  rankingUnavailable = null,
  stages = [],
  result = null,
  jenkinsUrl = null,
}: {
  /** The job the card follows, such as fs-payment-service-build. */
  jobName: string;
  /** Set while the run waits in the queue. */
  queue?: RunQueue | null;
  /** Why the queue position is unknown, when the plugin could not be read. */
  rankingUnavailable?: string | null;
  stages?: readonly RunStage[];
  result?: { state: BuildState; durationMs: number | null } | null;
  jenkinsUrl?: string | null;
}) {
  return (
    <section aria-label={`Run of ${jobName}`} className="flex flex-col gap-3 border border-rule p-4">
      <p className="font-semibold">{jobName}</p>

      {queue ? (
        <div className="flex flex-col gap-2">
          <p className="tabular-nums">{`${ordinal(queue.rank)} in queue`}</p>
          <ScoreBar size="card" score={queue.score} parts={queue.parts} weights={queue.weights} />
          <p className="text-sm text-graphite">{queue.waitingReason ?? WAITING}</p>
        </div>
      ) : rankingUnavailable ? (
        <p className="text-sm">
          <span className="font-semibold">Ranking unavailable. </span>
          <span className="text-graphite">{rankingUnavailable}</span>
        </p>
      ) : null}

      {stages.length > 0 ? (
        <ol aria-label="Stages" className="flex flex-wrap gap-x-4 gap-y-1">
          {stages.map(({ name, state }) => (
            <li key={name}>
              <BuildStateLabel state={state} label={`${name} ${stageWord(state)}`} />
            </li>
          ))}
        </ol>
      ) : null}

      {result ? (
        <p className="flex flex-wrap items-center gap-x-2">
          <BuildStateLabel state={result.state} className="font-semibold" />
          {result.durationMs === null ? null : (
            <span className="tabular-nums">{`in ${formatDuration(result.durationMs)}`}</span>
          )}
        </p>
      ) : null}

      {jenkinsUrl && isWebAddress(jenkinsUrl) ? (
        <a
          href={jenkinsUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 self-start font-semibold underline underline-offset-4"
        >
          Open in Jenkins
          <ExternalLink aria-hidden="true" className="size-4" />
          {/* Inline names join without spaces, so the comma carries the pause. */}
          <span className="sr-only">, opens in a new tab</span>
        </a>
      ) : null}
    </section>
  );
}

/** A stage not reached yet has not started; "not built" is Jenkins' word for a job. */
function stageWord(state: BuildState): string {
  return state === "not-built" ? "not started" : BUILD_STATES[state].word.toLowerCase();
}
