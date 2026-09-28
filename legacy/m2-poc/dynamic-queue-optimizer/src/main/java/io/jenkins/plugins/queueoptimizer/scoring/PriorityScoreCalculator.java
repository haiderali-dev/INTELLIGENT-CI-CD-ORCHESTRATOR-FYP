package io.jenkins.plugins.queueoptimizer.scoring;

import hudson.model.Queue;
import io.jenkins.plugins.queueoptimizer.dependency.DependencyResolver;
import io.jenkins.plugins.queueoptimizer.estimation.ExecutionTimeEstimator;
import io.jenkins.plugins.queueoptimizer.model.JobPriority;
import io.jenkins.plugins.queueoptimizer.model.ScoredJob;

import java.util.Collection;
import java.util.List;
import java.util.logging.Logger;

/**
 * Calculates the final Priority Score for a Jenkins queue item.
 *
 * Formula:
 *   PriorityScore = (W_urgency × UrgencyScore)
 *                 + (W_execTime × ExecutionTimeScore)
 *                 + (W_dependency × DependencyScore)
 *
 * Default weights: 0.50 / 0.30 / 0.20  (sum = 1.0)
 *
 * ExecutionTimeScore uses a Shortest-Job-First principle:
 *   shorter estimated duration → higher score.
 */
public class PriorityScoreCalculator {

    private static final Logger LOGGER =
            Logger.getLogger(PriorityScoreCalculator.class.getName());

    // --- Weights (must sum to 1.0) ---
    private static final double W_URGENCY    = 0.50;
    private static final double W_EXEC_TIME  = 0.30;
    private static final double W_DEPENDENCY = 0.20;

    private final ExecutionTimeEstimator timeEstimator;
    private final DependencyResolver     dependencyResolver;

    public PriorityScoreCalculator(ExecutionTimeEstimator timeEstimator,
                                   DependencyResolver dependencyResolver) {
        this.timeEstimator      = timeEstimator;
        this.dependencyResolver = dependencyResolver;
    }

    /**
     * Production entry-point: calculates the priority score for a real Jenkins queue item.
     *
     * @param item           The Jenkins queue item being evaluated.
     * @param priority       The user-selected priority (HIGH / MEDIUM / LOW).
     * @param allQueuedItems All items currently in the queue (for normalising exec-time score).
     */
    public ScoredJob calculate(Queue.BuildableItem item,
                               JobPriority priority,
                               Collection<Queue.BuildableItem> allQueuedItems) {

        // Extract job name and peer names, then delegate to the testable core method
        String jobName = item.task.getFullDisplayName();

        List<String> peerNames = allQueuedItems.stream()
                .map(i -> i.task.getFullDisplayName())
                .collect(java.util.stream.Collectors.toList());

        return calculateByName(item, jobName, priority, peerNames);
    }

    /**
     * Testable core method — uses only plain Java types so unit tests need
     * no Jenkins runtime classes at all.
     *
     * @param item      Real queue item (may be null in tests — only used to build ScoredJob).
     * @param jobName   Full display name of the job being scored.
     * @param priority  User-selected priority level.
     * @param peerNames Names of all other jobs currently in the queue.
     */
    ScoredJob calculateByName(Queue.BuildableItem item,
                              String jobName,
                              JobPriority priority,
                              Collection<String> peerNames) {

        // --- Component 1: Urgency ---
        double urgencyScore = priority.getUrgencyScore();

        // --- Component 2: Execution time (shorter = higher score) ---
        double estimatedSeconds = timeEstimator.estimate(jobName);
        double execTimeScore    = buildExecutionTimeScore(estimatedSeconds, peerNames);

        // --- Component 3: Dependency state ---
        double dependencyScore = dependencyResolver.calculateDependencyScore(jobName);
        boolean hasDeps        = !dependencyResolver.getUpstreamDependencies(jobName).isEmpty();

        // --- Final weighted score ---
        double finalScore = (W_URGENCY    * urgencyScore)
                          + (W_EXEC_TIME  * execTimeScore)
                          + (W_DEPENDENCY * dependencyScore);

        LOGGER.fine(String.format(
                "Score[%s]: urgency=%.0f(×%.2f) + execTime=%.1f(×%.2f) + dep=%.0f(×%.2f) = %.2f",
                jobName,
                urgencyScore,    W_URGENCY,
                execTimeScore,   W_EXEC_TIME,
                dependencyScore, W_DEPENDENCY,
                finalScore));

        if (item != null) {
            return new ScoredJob(item, finalScore, estimatedSeconds, hasDeps);
        }
        // Test path: build ScoredJob without a real Queue.BuildableItem
        return new ScoredJob(0L, jobName, finalScore, estimatedSeconds, hasDeps);
    }

    /**
     * Converts estimated execution time to a 0–100 score via inverse normalisation.
     *
     *   score = 100 × (1 − estimatedTime / maxTimeAmongPeers)
     *
     * A 10 s job in a queue where the slowest job takes 100 s → score = 90.
     * A 90 s job in the same queue → score = 10.
     */
    private double buildExecutionTimeScore(double estimatedSeconds,
                                           Collection<String> peerNames) {
        double maxTime = estimatedSeconds;

        for (String peer : peerNames) {
            double peerTime = timeEstimator.estimate(peer);
            if (peerTime > maxTime) maxTime = peerTime;
        }

        if (maxTime <= 0) return 50.0;

        return 100.0 * (1.0 - (estimatedSeconds / maxTime));
    }
}
