import { useId } from "react";

import type { Queue, QueueItem, UnscoredItem } from "@/api/queueApi";
import { ScoreBar } from "@/components/ScoreBar";
import { contributions, FACTORS } from "@/components/scoreBarModel";
import { cn } from "@/lib/cn";
import { formatScore } from "@/lib/format";

import { formatEstimate, formatWait, jobTypeLabel, missingUpstreamNote } from "./queueModel";

interface RankingProps {
  items: readonly QueueItem[];
  weights: Queue["weights"];
  /** The four contributions as numbers, beside each bar. */
  showNumbers: boolean;
  /** The bars grow once, on the page's first load. */
  grow: boolean;
}

const LABEL = "Waiting jobs, ranked by score, highest first";

/**
 * One row per ranked item, each explaining its own rank with its score bar, and saying why it is not
 * running yet (DESIGN.md section 4, Queue). A table from 768 px; below that, a stacked block per
 * item with the bar on its own line.
 */
export function QueueRanking({ wide, ...props }: RankingProps & { wide: boolean }) {
  return wide ? <RankingTable {...props} /> : <RankingList {...props} />;
}

// The first and last columns line up with the page's 24px gutter, and the rules between rows still
// run edge to edge.
const HEAD = "px-2 py-2 text-left text-sm font-semibold text-graphite first:pl-6 last:pr-6";
const CELL = "px-2 py-2 first:pl-6 last:pr-6";

function RankingTable({ items, weights, showNumbers, grow }: RankingProps) {
  return (
    // A table wider than its box scrolls inside it, never the page (DESIGN.md section 8), and its
    // rows stay one line: a job name never breaks, and a blocked reason keeps a readable width.
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{LABEL}</caption>
        <thead>
          <tr className="border-b border-rule">
            <th scope="col" className={cn(HEAD, "text-right")}>
              Rank
            </th>
            <th scope="col" className={HEAD}>
              Job
            </th>
            <th scope="col" className={HEAD}>
              Type
            </th>
            <th scope="col" className={HEAD}>
              Urgency
            </th>
            <th scope="col" className={HEAD}>
              Score
            </th>
            {showNumbers
              ? FACTORS.map(({ key, name, fill }) => (
                  // These headers may wrap; the numbers under them are five characters wide.
                  <th key={key} scope="col" className={cn(HEAD, "text-right")}>
                    <span className="inline-flex items-center gap-1.5">
                      <span aria-hidden="true" className={cn("size-2.5 rounded-control", fill)} />
                      {`From ${name}`}
                    </span>
                  </th>
                ))
              : null}
            <th scope="col" className={cn(HEAD, "text-right")}>
              Estimate
            </th>
            <th scope="col" className={cn(HEAD, "text-right")}>
              Wait
            </th>
            <th scope="col" className={HEAD}>
              Blocked reason
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const shares = contributions(item.components, weights);
            const missing = missingUpstreamNote(item);
            return (
              <tr key={item.item_id} className="border-b border-rule hover:bg-ground">
                <td className={cn(CELL, "h-10 text-right font-semibold tabular-nums")}>
                  {item.rank}
                </td>
                <th scope="row" className={cn(CELL, "text-left font-normal whitespace-nowrap")}>
                  {item.job_name}
                  {missing ? (
                    <span className="block whitespace-normal text-graphite">{missing}</span>
                  ) : null}
                </th>
                <td className={cn(CELL, "whitespace-nowrap")}>{jobTypeLabel(item.job_type)}</td>
                <td className={CELL}>{item.level}</td>
                <td className={cn(CELL, "whitespace-nowrap")}>
                  <ScoreBar
                    score={item.score}
                    parts={item.components}
                    weights={weights}
                    grow={grow}
                  />
                </td>
                {showNumbers
                  ? FACTORS.map(({ key }) => (
                      <td key={key} className={cn(CELL, "text-right tabular-nums")}>
                        {shares ? formatScore(shares[key]) : null}
                      </td>
                    ))
                  : null}
                <td className={cn(CELL, "text-right whitespace-nowrap tabular-nums")}>
                  {formatEstimate(item.estimate_seconds)}
                </td>
                <td className={cn(CELL, "text-right whitespace-nowrap tabular-nums")}>
                  {formatWait(item.wait_seconds)}
                </td>
                <td className={cn(CELL, "min-w-[28ch] text-graphite")}>{item.blocked_reason}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RankingList({ items, weights, showNumbers, grow }: RankingProps) {
  return (
    <ol aria-label={LABEL} className="flex flex-col">
      {items.map((item) => {
        const shares = contributions(item.components, weights);
        const missing = missingUpstreamNote(item);
        return (
          <li key={item.item_id} className="flex flex-col gap-2 border-b border-rule px-6 py-3">
            <p className="flex items-baseline gap-3 font-semibold">
              <span className="tabular-nums">{item.rank}</span>
              <span className="min-w-0">{item.job_name}</span>
            </p>
            <ScoreBar score={item.score} parts={item.components} weights={weights} grow={grow} />
            <dl className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              <Fact label="Type" value={jobTypeLabel(item.job_type)} />
              <Fact label="Urgency" value={item.level} />
              <Fact label="Estimate" value={formatEstimate(item.estimate_seconds)} />
              <Fact label="Wait" value={formatWait(item.wait_seconds)} />
              {showNumbers && shares
                ? FACTORS.map(({ key, name }) => (
                    <Fact key={key} label={`From ${name}`} value={formatScore(shares[key])} />
                  ))
                : null}
            </dl>
            {missing ? <p className="text-sm">{missing}</p> : null}
            {item.blocked_reason ? (
              <p className="text-sm text-graphite">{item.blocked_reason}</p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/** A labelled fact, never a run of values joined by dots (DESIGN.md section 9). */
function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1.5">
      <dt className="text-graphite">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * Queued work the plugin has not scored, listed so it is never silently missing. Its count is part
 * of the header's "waiting".
 */
export function UnscoredItems({ items }: { items: readonly UnscoredItem[] }) {
  const headingId = useId();
  if (items.length === 0) {
    return null;
  }
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-2 px-6 py-5">
      <h2 id={headingId} className="text-lg font-semibold">
        Waiting without a score
      </h2>
      <p className="max-w-[68ch] text-graphite">
        In the queue, but with no score, so they have no rank on this page.
      </p>
      <ul className="flex flex-col text-sm">
        {items.map((item) => (
          <li
            key={item.item_id}
            className="flex flex-wrap gap-x-4 gap-y-1 border-b border-rule py-2 last:border-b-0"
          >
            <span>{item.job_name}</span>
            <span className="text-graphite">{capitalised(item.reason)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The plugin's reasons start in lower case, to sit inside a sentence. Standing alone, they start a
 * sentence of their own. */
function capitalised(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
