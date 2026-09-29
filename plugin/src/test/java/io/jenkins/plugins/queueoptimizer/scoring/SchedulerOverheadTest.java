package io.jenkins.plugins.queueoptimizer.scoring;

import static org.junit.jupiter.api.Assertions.assertTrue;

import io.jenkins.plugins.queueoptimizer.heap.PriorityJobHeap;
import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.ArrayList;
import java.util.List;
import java.util.OptionalLong;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Required by BUILD_PROMPT 4.3.10: sorting 200 items stays under 5 ms.
 *
 * <p>The budget exists because this code runs inside Jenkins queue maintenance, on the thread that
 * decides what to build next. Milestone 2's scoring was O(n³) before a per-pass memo fixed it,
 * which is the kind of regression that only shows up under a full queue and is invisible in a
 * two-job test.
 *
 * <p>A timing assertion in a unit test is inherently machine-dependent, so this is written to fail
 * only on a real algorithmic regression rather than on a slow or busy machine: the JIT is warmed
 * first, the best of several runs is taken rather than an average, and the headroom against the
 * budget is large. A complexity regression costs orders of magnitude, not percent. The scaling
 * check below is the stronger signal and needs no absolute budget at all.
 */
class SchedulerOverheadTest {

    /** The budget from BUILD_PROMPT 4.3.10. */
    private static final long BUDGET_MILLIS = 5;

    private static final int ITEMS = 200;
    private static final int WARMUP_RUNS = 50;
    private static final int MEASURED_RUNS = 20;

    /**
     * A queue of {@code n} items with a realistic mix: three bands, varied estimates, some grouped
     * into dependency chains and some independent, and a few with no estimate at all.
     */
    private static List<ScoreInput> queueOf(int n) {
        List<ScoreInput> items = new ArrayList<>(n);
        for (int i = 0; i < n; i++) {
            PriorityLevel level =
                    switch (i % 3) {
                        case 0 -> PriorityLevel.HIGH;
                        case 1 -> PriorityLevel.MEDIUM;
                        default -> PriorityLevel.LOW;
                    };
            // Every fifth item joins a three-member group; the rest are independent.
            boolean grouped = i % 5 == 0;
            String groupId = grouped ? "group-" + (i / 15) : "solo-" + i;
            int groupSize = grouped ? 3 : 1;
            // Every seventh item has no usable history, exercising the UNKNOWN path.
            OptionalLong estimate = i % 7 == 0 ? OptionalLong.empty() : OptionalLong.of(1000L + (i * 137L) % 600_000L);

            items.add(new ScoreInput(
                    i,
                    "job-" + i + "-service-" + (i % 11),
                    level,
                    groupId,
                    groupSize,
                    grouped ? i % 3 : 0,
                    estimate,
                    (i * 37L) % 1_800_000L,
                    i));
        }
        return items;
    }

    /** Scores, sorts and heaps one queue, returning the elapsed nanoseconds. */
    private static long timeOnePass(List<ScoreInput> queue) {
        long start = System.nanoTime();
        List<ScoredJob> scored = PriorityScoreCalculator.withReportDefaults().scoreAll(queue);
        scored.sort(PriorityScoreCalculator.compareForDispatch());
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.replaceAll(scored);
        long elapsed = System.nanoTime() - start;

        // Consume the result so nothing can be optimised away.
        assertTrue(heap.size() == queue.size() && !scored.isEmpty());
        return elapsed;
    }

    private static long bestOf(int items, int runs) {
        List<ScoreInput> queue = queueOf(items);
        long best = Long.MAX_VALUE;
        for (int i = 0; i < runs; i++) {
            best = Math.min(best, timeOnePass(queue));
        }
        return best;
    }

    @Test
    @DisplayName("scoring and sorting 200 queued items stays within the 5 ms budget")
    void twoHundredItemsUnderBudget() {
        List<ScoreInput> queue = queueOf(ITEMS);
        for (int i = 0; i < WARMUP_RUNS; i++) {
            timeOnePass(queue);
        }

        long bestNanos = bestOf(ITEMS, MEASURED_RUNS);
        double bestMillis = bestNanos / 1_000_000.0;

        assertTrue(
                bestMillis < BUDGET_MILLIS,
                String.format(
                        "scoring, sorting and heaping %d items took %.3f ms, over the %d ms budget. "
                                + "This runs inside queue maintenance, so it delays every "
                                + "scheduling decision.",
                        ITEMS, bestMillis, BUDGET_MILLIS));
    }

    @Test
    @DisplayName("cost grows about linearly, not quadratically, with queue length")
    void costScalesLinearly() {
        // The real regression guard, and machine-independent because it compares the
        // implementation against itself. Milestone 2's scoring was O(n^3); at these sizes that
        // would be unmistakable.
        for (int i = 0; i < WARMUP_RUNS; i++) {
            timeOnePass(queueOf(100));
        }

        long small = bestOf(100, MEASURED_RUNS);
        long large = bestOf(400, MEASURED_RUNS);

        // Four times the items. Linear plus the sort's log factor lands near 4-5x; quadratic would
        // be about 16x and cubic about 64x. A ceiling of 10x fails a complexity regression while
        // leaving ample room for measurement noise.
        double ratio = (double) large / Math.max(1, small);
        assertTrue(
                ratio < 10.0,
                String.format(
                        "quadrupling the queue multiplied the cost by %.1fx (%d ns -> %d ns). "
                                + "Linear-ish is expected; this looks super-linear, which is how "
                                + "the Milestone 2 O(n^3) scoring behaved.",
                        ratio, small, large));
    }

    @Test
    @DisplayName("a large queue produces a complete, totally ordered result")
    void largeQueueStaysCorrect() {
        // Speed is worthless if the answer is wrong, and a partial sort is the likely failure mode
        // of an optimisation attempt here.
        List<ScoreInput> queue = queueOf(ITEMS);
        List<ScoredJob> scored = PriorityScoreCalculator.withReportDefaults().scoreAll(queue);
        scored.sort(PriorityScoreCalculator.compareForDispatch());

        assertTrue(scored.size() == ITEMS, "every item must be scored");
        for (int i = 1; i < scored.size(); i++) {
            assertTrue(
                    scored.get(i - 1).score() >= scored.get(i).score(), "scores must be non-increasing at index " + i);
        }
        assertTrue(
                scored.stream().map(ScoredJob::itemId).distinct().count() == ITEMS,
                "no item may be dropped or duplicated");
    }
}
