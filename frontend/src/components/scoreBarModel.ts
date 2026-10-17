/**
 * The score bar's arithmetic (DESIGN.md section 6), apart from its drawing so it can be checked
 * exactly.
 *
 * Each segment is weight times factor, with the weights taken from the queue API, which reports the
 * plugin's own. They are never written into the UI: if the weights change, the bars change with
 * them. Aging is a bonus with no weight.
 */

import type { components } from "@/api/schema";
import { formatScore } from "@/lib/format";

export type ScoreComponents = components["schemas"]["ScoreComponentsResponse"];
/** The plugin's weights as the queue API reports them: `urgency`, `dependency`, `executionTime`. */
export type ScoreWeights = components["schemas"]["QueueResponse"]["weights"];

/** The fixed scale: three weights that sum to 1.0, plus aging's cap of 0.15. */
export const SCALE_MAX = 1.15;
/** Below half a unit of the third decimal, a difference is rounding, not inheritance. */
const INHERITED_EPSILON = 0.0005;

export type Factor = "urgency" | "dependency" | "executionTime" | "aging";

/** The formula's order, 0.5U + 0.3D + 0.2T and then aging. The hues never move. `name` sits
 * inside a sentence; `label` starts one. */
export const FACTORS: readonly { key: Factor; name: string; label: string; fill: string }[] = [
  { key: "urgency", name: "urgency", label: "Urgency", fill: "bg-factor-urgency" },
  { key: "dependency", name: "dependency", label: "Dependency", fill: "bg-factor-dependency" },
  {
    key: "executionTime",
    name: "execution time",
    label: "Execution time",
    fill: "bg-factor-execution-time",
  },
  { key: "aging", name: "aging", label: "Aging", fill: "bg-factor-aging" },
];

export type Contributions = Record<Factor, number>;

/** Each factor's part of the score, or null when the weights are missing: the UI never guesses. */
export function contributions(
  parts: ScoreComponents,
  weights: ScoreWeights,
): Contributions | null {
  const { urgency, dependency, executionTime } = weights;
  if (urgency === undefined || dependency === undefined || executionTime === undefined) {
    return null;
  }
  return {
    urgency: urgency * parts.urgency,
    dependency: dependency * parts.dependency,
    executionTime: executionTime * parts.execution_time,
    aging: parts.aging_bonus,
  };
}

/** The job's own score, before group inheritance: base plus aging, as the plugin reports it. */
export function ownScore(parts: ScoreComponents): number {
  return parts.own_score;
}

/** True when the effective score came from a stronger member of the job's group. */
export function isInherited(score: number, parts: ScoreComponents): boolean {
  return score > ownScore(parts) + INHERITED_EPSILON;
}

/** The bar's accessible name and tooltip, worded as DESIGN.md section 6 gives it. */
export function describeScore(
  score: number,
  parts: ScoreComponents,
  shares: Contributions,
): string {
  const list = FACTORS.map(({ key, name }) => `${name} ${formatScore(shares[key])}`).join(", ");
  if (isInherited(score, parts)) {
    return `Score ${formatScore(score)}, inherited from its group. Own score ${formatScore(ownScore(parts))}: ${list}.`;
  }
  return `Score ${formatScore(score)}: ${list}.`;
}

/** A value's place on the 0 to 1.15 scale, as a percentage of the bar's width. */
export function percentOfScale(value: number): number {
  return (Math.min(Math.max(value, 0), SCALE_MAX) / SCALE_MAX) * 100;
}

export interface Segment {
  key: Factor;
  fill: string;
  startPercent: number;
  widthPercent: number;
  /** The data end, which alone has rounded corners. */
  last: boolean;
}

/** The segments to draw, left to right. A factor of zero draws nothing and leaves no gap. */
export function segments(shares: Contributions): Segment[] {
  const drawn = FACTORS.filter(({ key }) => shares[key] > 0);
  let start = 0;
  return drawn.map(({ key, fill }, index) => {
    const segment = {
      key,
      fill,
      startPercent: percentOfScale(start),
      widthPercent: percentOfScale(start + shares[key]) - percentOfScale(start),
      last: index === drawn.length - 1,
    };
    start += shares[key];
    return segment;
  });
}

/** Where the drawn segments end, and the empty track begins. */
export function endPercent(shares: Contributions): number {
  return percentOfScale(FACTORS.reduce((sum, { key }) => sum + Math.max(shares[key], 0), 0));
}
