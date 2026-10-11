package io.jenkins.plugins.queueoptimizer.scoring;

import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.OptionalLong;

/**
 * One scored queue item, keeping every intermediate value.
 *
 * <p>The intermediate values are not debugging leftovers. The ranking API returns them, the
 * frontend's score bar draws them as stacked segments answering "why is my build not running
 * yet", and {@code AppendixCExampleTest} asserts them individually. A score that can only be
 * reported as one number is a score nobody can argue with, which is the opposite of what the
 * report needs to defend.
 *
 * @param itemId the queue item id
 * @param jobName the job's full name
 * @param level the configured urgency
 * @param urgencyFactor {@code U}, the level's normalised value
 * @param dependencyFactor {@code D}, from group size against the largest group
 * @param executionTimeFactor {@code T}, shorter estimates scoring higher
 * @param baseScore {@code wU*U + wD*D + wT*T}, before aging and group inheritance
 * @param agingBonus the anti-starvation bonus for time already waited
 * @param ownScore {@code baseScore + agingBonus}, this item's own merit
 * @param score the effective score after group inheritance; what the queue is ordered by
 * @param estimateMillis the estimate used, empty when unknown
 * @param groupId the dependency group
 * @param groupSize the number of queued members in that group
 * @param topologicalRank position within the group, producers first
 * @param inQueueSince the enqueue timestamp
 */
public record ScoredJob(
        long itemId,
        String jobName,
        PriorityLevel level,
        double urgencyFactor,
        double dependencyFactor,
        double executionTimeFactor,
        double baseScore,
        double agingBonus,
        double ownScore,
        double score,
        OptionalLong estimateMillis,
        String groupId,
        int groupSize,
        int topologicalRank,
        long inQueueSince) {

    /** @return true when this item's effective score came from a stronger group member */
    public boolean inheritedGroupScore() {
        return score > ownScore;
    }

    /** @return true when no usable duration history was found, so {@code T} used the neutral 0.5 */
    public boolean hasUnknownEstimate() {
        return estimateMillis.isEmpty();
    }

    /** A copy with the effective score replaced, used when a group lifts its members. */
    ScoredJob withInheritedScore(double inherited) {
        return new ScoredJob(
                itemId,
                jobName,
                level,
                urgencyFactor,
                dependencyFactor,
                executionTimeFactor,
                baseScore,
                agingBonus,
                ownScore,
                inherited,
                estimateMillis,
                groupId,
                groupSize,
                topologicalRank,
                inQueueSince);
    }
}
