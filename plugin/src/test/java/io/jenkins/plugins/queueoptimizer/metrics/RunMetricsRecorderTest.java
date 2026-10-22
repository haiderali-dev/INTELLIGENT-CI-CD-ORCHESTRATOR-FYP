package io.jenkins.plugins.queueoptimizer.metrics;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Regression test for DF-45: a build's executor waits are its own, not its job's.
 *
 * <p>The recorder's ring holds the last 500 events, so it also holds earlier builds of the same
 * job: the experiment's warm-up runs, and every repetition before this one. Matching QUEUE_LEFT
 * events on the job name alone summed those earlier waits into the build being completed, which
 * would have corrupted BUILD_PROMPT 4.8.4's Pipeline figures, the first node block's wait and the
 * sum of all of them.
 */
class RunMetricsRecorderTest {

    private static MetricEvent left(
            String job, long itemId, long inQueueSince, long waitMillis, boolean nodeBlock, boolean consumesExecutor) {
        return MetricEvent.of(MetricEvent.Kind.QUEUE_LEFT)
                .with("itemId", itemId)
                .with("jobName", job)
                .with("isNodeBlock", nodeBlock)
                .with("consumesExecutor", consumesExecutor)
                .with("inQueueSince", inQueueSince)
                .with("waitMillis", waitMillis)
                .with("cancelled", false);
    }

    @Test
    @DisplayName("a freestyle build counts only its own queue item, not an earlier build's")
    void freestyleBuildCountsOnlyItsOwnItem() {
        List<MetricEvent> ring = List.of(
                left("api", 1, 1_000, 5_000, false, true), // the previous build
                left("api", 2, 20_000, 700, false, true)); // this build, queue item 2

        RunMetricsRecorder.NodeBlockWaits waits = RunMetricsRecorder.nodeBlockWaits(ring, "api", 2, 20_700);

        assertEquals(new RunMetricsRecorder.NodeBlockWaits(700, 700, 1), waits);
    }

    @Test
    @DisplayName("a Pipeline build counts the node blocks it queued, not an earlier build's or its flyweight")
    void pipelineBuildCountsOnlyItsNodeBlocks() {
        List<MetricEvent> ring = List.of(
                left("deploy", 10, 2_000, 3_000, true, true), // the previous build's node block
                left("deploy", 20, 30_000, 9_000, false, false), // this build's flyweight task
                left("deploy", 21, 40_000, 400, true, true), // this build's first node block
                left("deploy", 22, 41_000, 600, true, true)); // and its second

        RunMetricsRecorder.NodeBlockWaits waits = RunMetricsRecorder.nodeBlockWaits(ring, "deploy", 20, 39_000);

        assertEquals(new RunMetricsRecorder.NodeBlockWaits(400, 1_000, 2), waits);
    }

    @Test
    @DisplayName("another job's items and a cancelled item are never counted")
    void otherJobsAndCancelledItemsAreIgnored() {
        MetricEvent cancelled = left("api", 3, 20_000, 900, false, true).with("cancelled", true);
        List<MetricEvent> ring = List.of(
                left("other", 2, 20_000, 1_200, false, true), // same queue id, another job's
                cancelled,
                left("api", 2, 20_000, 700, false, true));

        RunMetricsRecorder.NodeBlockWaits waits = RunMetricsRecorder.nodeBlockWaits(ring, "api", 2, 20_700);

        assertEquals(new RunMetricsRecorder.NodeBlockWaits(700, 700, 1), waits);
    }

    @Test
    @DisplayName("a build with no recorded wait reports zeros, not a negative first wait")
    void noWaitReportsZeros() {
        assertEquals(
                new RunMetricsRecorder.NodeBlockWaits(0, 0, 0),
                RunMetricsRecorder.nodeBlockWaits(List.of(), "api", 2, 20_700));
    }
}
