package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Required by BUILD_PROMPT 4.3.10: draining 20 jobs over many cycles never degrades to arrival order.
 *
 * <p>This test exists because the failure it guards against actually happened and was published.
 * Milestone 2's dispatcher cached scores per maintenance cycle, then a change skipped repopulating
 * the heap on a cache hit. The heap drained as items left the queue, the optimizer silently fell
 * back to arrival order, and the plugin went on reporting itself as enabled.
 *
 * <p>The only surviving evidence is one result file:
 * {@code legacy/m2-poc/experiment/results/plugin-results-run3.json} records a HIGH-band wait of
 * 353.34 s against a FIFO baseline of 271.50 s — worse than the thing it was meant to beat, on the
 * metric it targeted — with a LOW-band wait near the baseline. That is the signature of arrival
 * order. Nothing caught it, because there was no dispatcher test at all. See
 * {@code docs/m2-baseline.md} section 3.2.
 *
 * <p>A short queue cannot detect this: the degradation only appears once enough maintenance cycles
 * have run for the heap to drain. Hence twenty jobs and a single executor, so the queue is re-sorted
 * on every dispatch.
 */
@WithJenkins
class CacheEvictionRegressionIT {

    private static final int LOW_JOBS = 10;
    private static final int HIGH_JOBS = 10;

    @Test
    @DisplayName("draining 20 jobs on one executor keeps priority order throughout")
    void drainingTwentyJobsKeepsPriorityOrder(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        // All ten LOW jobs arrive first, so arrival order and priority order are exact opposites.
        // Under the Milestone 2 regression the output would come back in submission order.
        List<String> lows = new ArrayList<>();
        List<String> highs = new ArrayList<>();
        for (int i = 1; i <= LOW_JOBS; i++) {
            String name = String.format("drain-low-%02d", i);
            lows.add(name);
            schedule(j, name, "LOW");
        }
        for (int i = 1; i <= HIGH_JOBS; i++) {
            String name = String.format("drain-high-%02d", i);
            highs.add(name);
            schedule(j, name, "HIGH");
        }
        waitUntilBuildable(j, LOW_JOBS + HIGH_JOBS);

        // One executor, so every single dispatch is preceded by a fresh maintenance pass. Twenty
        // jobs therefore means twenty sorts, which is what exercises the cache across cycles.
        j.jenkins.setNumExecutors(1);
        List<String> all = new ArrayList<>(lows);
        all.addAll(highs);
        waitUntilAllComplete(j, all);

        List<String> order = dispatches.order();

        // Every HIGH job must be dispatched before every LOW job. Asserted as a partition rather
        // than an exact permutation, since order within a band is not meaningful.
        int lastHigh = highs.stream().mapToInt(order::indexOf).max().orElseThrow();
        int firstLow = lows.stream().mapToInt(order::indexOf).min().orElseThrow();

        assertTrue(
                lastHigh < firstLow,
                "the queue degraded to arrival order partway through the drain. This is the "
                        + "Milestone 2 regression: the heap was not repopulated on a cache hit, so "
                        + "it drained as items left and the optimizer silently became FIFO.\n"
                        + "  last HIGH dispatched at index " + lastHigh
                        + ", first LOW at index " + firstLow
                        + "\n  observed order: " + order);
    }

    @Test
    @DisplayName("the heap is rebuilt on a cache hit, not only on a miss")
    void heapIsRebuiltOnCacheHit(JenkinsRule j) throws Exception {
        // The mechanism directly. Two maintenance passes with an unchanged item set inside the same
        // minute produce a cache hit; the heap must still hold every item afterwards. Milestone 2's
        // bug was that the second pass left the heap as the first had emptied it.
        j.jenkins.setNumExecutors(0);
        for (int i = 1; i <= 4; i++) {
            schedule(j, "hit-job-" + i, i % 2 == 0 ? "HIGH" : "LOW");
        }
        waitUntilBuildable(j, 4);

        j.jenkins.getQueue().maintain();
        int afterFirstPass = DynamicQueueSorter.getHeap().size();

        // Same items, same minute: this pass should hit the score cache.
        j.jenkins.getQueue().maintain();
        int afterSecondPass = DynamicQueueSorter.getHeap().size();

        assertTrue(afterFirstPass >= 4, "the first pass should have scored all four items, got " + afterFirstPass);
        assertTrue(
                afterSecondPass >= 4,
                "the heap emptied across a cached pass (" + afterFirstPass + " then " + afterSecondPass
                        + "). A cache hit must still rebuild the heap.");

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("hit-job-1", "hit-job-2", "hit-job-3", "hit-job-4"));
    }

    @Test
    @DisplayName("a job queued mid-drain is ranked, not appended")
    void lateArrivalIsRanked(JenkinsRule j) throws Exception {
        // Invalidating the cache has to re-rank rather than leave the newcomer at the back. A HIGH
        // job arriving while LOW work is still queued must overtake it.
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        List<String> lows = new ArrayList<>();
        for (int i = 1; i <= 6; i++) {
            String name = String.format("late-low-%02d", i);
            lows.add(name);
            schedule(j, name, "LOW");
        }
        waitUntilBuildable(j, 6);
        j.jenkins.getQueue().maintain();

        // Arrives last, outranks everything.
        schedule(j, "late-high", "HIGH");
        waitUntilBuildable(j, 7);

        j.jenkins.setNumExecutors(1);
        List<String> all = new ArrayList<>(lows);
        all.add("late-high");
        waitUntilAllComplete(j, all);

        List<String> order = dispatches.order();
        int high = order.indexOf("late-high");
        int firstLow = lows.stream().mapToInt(order::indexOf).min().orElseThrow();

        assertTrue(
                high < firstLow,
                "a HIGH job arriving mid-drain must be re-ranked ahead of queued LOW work, not "
                        + "appended. Got index " + high + " against first LOW at " + firstLow
                        + "\n  observed order: " + order);
    }

    private static void schedule(JenkinsRule j, String name, String level) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject(name);
        project.addProperty(new JobPriorityProperty(level, ""));
        project.scheduleBuild2(0);
    }
}
