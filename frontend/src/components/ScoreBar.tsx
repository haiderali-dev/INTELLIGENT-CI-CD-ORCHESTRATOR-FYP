import { Tooltip } from "radix-ui";

import { cn } from "@/lib/cn";
import { formatScore } from "@/lib/format";

import {
  contributions,
  describeScore,
  endPercent,
  FACTORS,
  isInherited,
  percentOfScale,
  segments,
  type Contributions,
  type ScoreComponents,
  type ScoreWeights,
} from "./scoreBarModel";

/** DESIGN.md section 6: a queue row is 160 x 12 px; a run card is full width, at most 480 x 16 px,
 * with a legend. */
export type ScoreBarSize = "row" | "card";

/**
 * The score bar, the one loud thing on the page (DESIGN.md principle 1). Four segments in a fixed
 * order and fixed hues on a fixed 0 to 1.15 scale, the score as a number beside it, a Graphite tick
 * at 1.0 and, when the score is inherited from the job's group, an Ink tick where it sits.
 */
export function ScoreBar({
  score,
  parts,
  weights,
  size = "row",
  className,
}: {
  score: number;
  parts: ScoreComponents;
  weights: ScoreWeights;
  size?: ScoreBarSize;
  className?: string;
}) {
  const shares = contributions(parts, weights);
  if (!shares) {
    return (
      <span className={cn("text-sm", className)}>
        <span className="font-semibold tabular-nums">{formatScore(score)}</span>
        <span className="text-graphite">
          {" "}
          Its parts cannot be shown: the plugin did not report its weights.
        </span>
      </span>
    );
  }

  const label = describeScore(score, parts, shares);
  const inherited = isInherited(score, parts);

  return (
    <span className={cn("flex flex-col gap-1", size === "row" && "inline-flex", className)}>
      <span className="flex items-center gap-2">
        <Tooltip.Provider delayDuration={200}>
          <Tooltip.Root>
            <Tooltip.Trigger asChild>
              <span
                role="img"
                aria-label={label}
                // Focus shows the same words as hover (DESIGN.md section 6).
                tabIndex={0}
                className={cn(
                  "relative block shrink-0",
                  size === "row" ? "h-3 w-40" : "h-4 w-full max-w-[480px]",
                )}
              >
                <Bar shares={shares} score={score} inherited={inherited} />
              </span>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                side="top"
                sideOffset={6}
                className="z-50 max-w-[40ch] rounded-float bg-panel px-3 py-2 text-sm text-ink shadow-float dark:border dark:border-rule"
              >
                {label}
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        </Tooltip.Provider>
        <span className="font-semibold tabular-nums">{formatScore(score)}</span>
        {inherited ? <span className="text-sm text-graphite">inherited</span> : null}
        {size === "row" ? (
          // Forced colours paint the segments over; the numbers say what they would have.
          <span className="hidden text-sm forced-colors:inline">
            <Numbers shares={shares} />
          </span>
        ) : null}
      </span>
      {size === "card" ? <Legend shares={shares} /> : null}
    </span>
  );
}

function Bar({
  shares,
  score,
  inherited,
}: {
  shares: Contributions;
  score: number;
  inherited: boolean;
}) {
  const drawn = segments(shares);
  return (
    <>
      {/* The empty track, a 1px Rule line out to 1.15. */}
      <span
        aria-hidden="true"
        className="absolute top-1/2 right-0 h-px -translate-y-1/2 bg-rule"
        style={{ left: `${endPercent(shares)}%` }}
      />
      {drawn.map(({ key, fill, startPercent, widthPercent, last }) => (
        <span
          key={key}
          aria-hidden="true"
          data-factor={key}
          className={cn("absolute inset-y-0", fill, last && "rounded-r-data")}
          style={{
            left: `${startPercent}%`,
            // A 2px gap of the surface between segments, never a stroke; a sliver is drawn at 2px.
            width: last ? `max(2px, ${widthPercent}%)` : `max(2px, calc(${widthPercent}% - 2px))`,
          }}
        />
      ))}
      <span
        aria-hidden="true"
        data-mark="ceiling"
        className="absolute -inset-y-0.5 w-px bg-graphite"
        style={{ left: `${percentOfScale(1)}%` }}
      />
      {inherited ? (
        <span
          aria-hidden="true"
          data-mark="inherited"
          className="absolute -inset-y-1 w-[2px] -translate-x-1/2 bg-ink"
          style={{ left: `${percentOfScale(score)}%` }}
        />
      ) : null}
    </>
  );
}

function Numbers({ shares }: { shares: Contributions }) {
  return FACTORS.map(({ key, name }) => `${name} ${formatScore(shares[key])}`).join(", ");
}

/** The run card's one-line legend. Keys carry the hue; the words stay in Ink and Graphite. */
function Legend({ shares }: { shares: Contributions }) {
  return (
    <span aria-hidden="true" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {FACTORS.map(({ key, label, fill }) => (
        <span key={key} className="inline-flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-control", fill)} />
          <span className="text-graphite">{label}</span>
          <span className="tabular-nums">{formatScore(shares[key])}</span>
        </span>
      ))}
    </span>
  );
}
