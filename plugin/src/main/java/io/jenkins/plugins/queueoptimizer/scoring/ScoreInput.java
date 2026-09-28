package io.jenkins.plugins.queueoptimizer.scoring;

import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.OptionalLong;

/**
 * Everything the scorer needs about one queued item, as plain data.
 *
 * <p>Plain data on purpose. BUILD_PROMPT's quality bar forbids Jenkins imports in the scoring
 * package, so the formula can be tested against the report's worked example with no Jenkins
 * runtime at all. The adapter from {@code Queue.Item} lives in the sorter, not here.
 *
 * @param itemId the queue item id, used as the final tie-break
 * @param jobName the job's full name, for diagnostics and the API
 * @param level the configured urgency
 * @param groupId the dependency group this item belongs to; a unique value when independent
 * @param groupSize the number of queued items in that group, 1 when independent
 * @param topologicalRank position within the group from Kahn's algorithm, 0 when independent
 * @param estimateMillis the estimated duration, or empty when history gives no usable answer
 * @param waitMillis how long the item has been queued, from {@code getInQueueSince()}
 * @param inQueueSince the enqueue timestamp, used to break ties before the item id
 */
public record ScoreInput(
        long itemId,
        String jobName,
        PriorityLevel level,
        String groupId,
        int groupSize,
        int topologicalRank,
        OptionalLong estimateMillis,
        long waitMillis,
        long inQueueSince) {

    /** A convenience for independent jobs with a known estimate. */
    public static ScoreInput independent(
            long itemId, String jobName, PriorityLevel level, long estimateMillis, long waitMillis) {
        return new ScoreInput(
                itemId, jobName, level, "solo-" + itemId, 1, 0, OptionalLong.of(estimateMillis), waitMillis, 0L);
    }

    /** A convenience for an independent job whose duration history gives nothing usable. */
    public static ScoreInput independentUnknownEstimate(
            long itemId, String jobName, PriorityLevel level, long waitMillis) {
        return new ScoreInput(itemId, jobName, level, "solo-" + itemId, 1, 0, OptionalLong.empty(), waitMillis, 0L);
    }
}
