package io.jenkins.plugins.queueoptimizer.scoring;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.OptionalLong;

/**
 * Report Algorithm 6.1, the weighted priority score.
 *
 * <pre>
 * U     = level value                       HIGH 1.0, MEDIUM 0.6, LOW 0.3
 * D     = groupSize &lt;= 1 ? 0 : (groupSize - 1) / (maxGroupSize - 1)
 * T     = estimate unknown ? 0.5
 *       : estMax == estMin ? 0.5
 *       : 1 - (est - estMin) / (estMax - estMin)
 * base  = 0.5 * U + 0.3 * D + 0.2 * T
 * aging = min(0.15, 0.05 * floor(waitMinutes / 5))
 * score = base + aging
 * if the item is in a group of size &gt; 1: score = max(score, best score in the group)
 * </pre>
 *
 * <p>This class is the reason {@code AppendixCExampleTest} exists. Milestone 2 published this
 * formula and implemented a different one: the dependency and execution-time weights were
 * transposed, urgency ran 100/50/10 on an unnormalised scale, and there was neither aging nor
 * group inheritance. Every score it ever produced was wrong with respect to its own report, and
 * no test would have noticed. See {@code docs/m2-baseline.md} section 4.3.
 *
 * <p>No Jenkins imports, by BUILD_PROMPT's quality bar, so the report's worked example can be
 * asserted directly against plain data.
 */
public final class PriorityScoreCalculator {

    /** The neutral execution-time factor, used when the estimate says nothing useful. */
    static final double NEUTRAL_EXECUTION_TIME_FACTOR = 0.5;

    private static final long MILLIS_PER_MINUTE = 60_000L;

    private final double weightUrgency;
    private final double weightDependency;
    private final double weightExecutionTime;
    private final double agingBonusPerInterval;
    private final int agingIntervalMinutes;
    private final double agingCap;

    public PriorityScoreCalculator(
            double weightUrgency,
            double weightDependency,
            double weightExecutionTime,
            double agingBonusPerInterval,
            int agingIntervalMinutes,
            double agingCap) {
        this.weightUrgency = weightUrgency;
        this.weightDependency = weightDependency;
        this.weightExecutionTime = weightExecutionTime;
        this.agingBonusPerInterval = agingBonusPerInterval;
        this.agingIntervalMinutes = agingIntervalMinutes;
        this.agingCap = agingCap;
    }

    /** A calculator using the report Appendix D defaults. */
    public static PriorityScoreCalculator withReportDefaults() {
        return new PriorityScoreCalculator(0.5, 0.3, 0.2, 0.05, 5, 0.15);
    }

    /**
     * Scores every item, normalising {@code D} and {@code T} across the whole set.
     *
     * <p>Both factors are relative, so an item cannot be scored alone: {@code D} compares its
     * group against the largest group present, and {@code T} places its estimate between the
     * shortest and longest present. The returned list is in the same order as the input;
     * ordering is {@link #compareForDispatch()}'s job.
     *
     * @param items the buildable items to score
     * @return one scored job per input item, with every intermediate value retained
     */
    public List<ScoredJob> scoreAll(List<ScoreInput> items) {
        if (items.isEmpty()) {
            return List.of();
        }

        int maxGroupSize = items.stream().mapToInt(ScoreInput::groupSize).max().orElse(1);

        // Only known estimates define the range. An unknown estimate takes the neutral factor
        // rather than being treated as zero, which would make an unmeasured job look fastest.
        long[] known = items.stream()
                .map(ScoreInput::estimateMillis)
                .filter(OptionalLong::isPresent)
                .mapToLong(OptionalLong::getAsLong)
                .toArray();
        long estMin = known.length == 0 ? 0 : java.util.Arrays.stream(known).min().getAsLong();
        long estMax = known.length == 0 ? 0 : java.util.Arrays.stream(known).max().getAsLong();

        List<ScoredJob> scored = new ArrayList<>(items.size());
        for (ScoreInput item : items) {
            scored.add(scoreOne(item, maxGroupSize, estMin, estMax, known.length > 0));
        }
        return applyGroupInheritance(scored);
    }

    private ScoredJob scoreOne(
            ScoreInput item, int maxGroupSize, long estMin, long estMax, boolean anyKnown) {
        double urgency = item.level().getUrgency();
        double dependency = dependencyFactor(item.groupSize(), maxGroupSize);
        double executionTime = executionTimeFactor(item.estimateMillis(), estMin, estMax, anyKnown);

        double base = weightUrgency * urgency
                + weightDependency * dependency
                + weightExecutionTime * executionTime;
        double aging = agingBonus(item.waitMillis());

        return new ScoredJob(
                item.itemId(),
                item.jobName(),
                item.level(),
                urgency,
                dependency,
                executionTime,
                base,
                aging,
                base + aging,
                base + aging,
                item.estimateMillis(),
                item.groupId(),
                item.groupSize(),
                item.topologicalRank(),
                item.inQueueSince());
    }

    /**
     * {@code D}: how much of the largest group's blocking power this item's group carries.
     *
     * <p>Zero for an independent job. One for a member of the largest group. When every group has
     * one member there is nothing to compare, so every item scores zero rather than one, which
     * keeps {@code D} from silently becoming a constant offset on a queue of independent jobs.
     */
    private static double dependencyFactor(int groupSize, int maxGroupSize) {
        if (groupSize <= 1 || maxGroupSize <= 1) {
            return 0.0;
        }
        return (double) (groupSize - 1) / (maxGroupSize - 1);
    }

    /**
     * {@code T}: shorter estimated durations score higher, a shortest-job-first nudge.
     *
     * <p>Returns the neutral 0.5 when the estimate is unknown, when nothing in the queue has a
     * usable estimate, and when every estimate is identical. That last case matters more than it
     * looks: {@code estMax == estMin} would divide by zero, and a queue of identical jobs is
     * exactly what the experiment's warm-up produces.
     */
    private static double executionTimeFactor(
            OptionalLong estimate, long estMin, long estMax, boolean anyKnown) {
        if (estimate.isEmpty() || !anyKnown || estMax == estMin) {
            return NEUTRAL_EXECUTION_TIME_FACTOR;
        }
        double span = (double) (estMax - estMin);
        return 1.0 - ((double) (estimate.getAsLong() - estMin) / span);
    }

    /**
     * The anti-starvation bonus: a step every interval, capped.
     *
     * <p>A step function rather than a smooth ramp, exactly as the report specifies. Without it,
     * a steady stream of HIGH arrivals starves LOW jobs indefinitely. Milestone 2 omitted this
     * entirely, and its LOW band paid for it: a mean wait of 233 s against a 16 s baseline.
     */
    private double agingBonus(long waitMillis) {
        if (waitMillis <= 0 || agingIntervalMinutes <= 0) {
            return 0.0;
        }
        long waitMinutes = waitMillis / MILLIS_PER_MINUTE;
        long intervals = waitMinutes / agingIntervalMinutes;
        return Math.min(agingCap, agingBonusPerInterval * intervals);
    }

    /**
     * Lifts every member of a multi-member group to that group's best score.
     *
     * <p>This is what makes a dependency chain move through the queue as one unit. Without it the
     * producer is scheduled on its own merit and its consumers drift behind other work, so the
     * group occupies the queue far longer than the sum of its parts.
     *
     * <p>Report Appendix C shows the effect: the LOW job {@code build-api} scores 0.650 and
     * overtakes a MEDIUM job, not on its own merit but because it unblocks a group whose best
     * member scores 0.633.
     */
    private static List<ScoredJob> applyGroupInheritance(List<ScoredJob> scored) {
        Map<String, Double> bestByGroup = new HashMap<>();
        Map<String, Integer> sizeByGroup = new HashMap<>();
        for (ScoredJob job : scored) {
            bestByGroup.merge(job.groupId(), job.ownScore(), Math::max);
            sizeByGroup.merge(job.groupId(), 1, Integer::sum);
        }

        List<ScoredJob> result = new ArrayList<>(scored.size());
        for (ScoredJob job : scored) {
            boolean isRealGroup = sizeByGroup.getOrDefault(job.groupId(), 1) > 1;
            double best = bestByGroup.getOrDefault(job.groupId(), job.ownScore());
            result.add(isRealGroup && best > job.ownScore() ? job.withInheritedScore(best) : job);
        }
        return result;
    }

    /**
     * Dispatch order: score descending, then group topological rank, then the tie-break.
     *
     * <p>The topological rank comes second so that members of a group sharing one inherited score
     * still run producer-first. Ties then fall to the earlier enqueue time and finally the lower
     * item id, which is what makes the order deterministic. Milestone 2 learned that the hard
     * way: without a total order, repeated heap rebuilds kept swapping which of several tied jobs
     * sat at the root, and no single item was ever reported as the top for a whole maintenance
     * cycle.
     *
     * <p>No rounding here. Scores are rounded only for display; rounding inside the comparator
     * would merge genuinely different scores into artificial ties.
     */
    public static Comparator<ScoredJob> compareForDispatch() {
        return Comparator.comparingDouble(ScoredJob::score)
                .reversed()
                .thenComparingInt(ScoredJob::topologicalRank)
                .thenComparingLong(ScoredJob::inQueueSince)
                .thenComparingLong(ScoredJob::itemId);
    }
}
