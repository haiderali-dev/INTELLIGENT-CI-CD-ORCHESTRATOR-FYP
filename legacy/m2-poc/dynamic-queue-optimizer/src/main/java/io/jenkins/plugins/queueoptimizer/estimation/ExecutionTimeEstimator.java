package io.jenkins.plugins.queueoptimizer.estimation;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Logger;

/**
 * Predicts how long a job will take to execute by analysing historical data.
 *
 * Estimation strategy (applied in order):
 *   1. Weighted Moving Average of the job's own past builds  (if >= 3 builds)
 *   2. Average duration of "similar" jobs                    (if similar exist)
 *   3. Global average across all Jenkins jobs                (last resort)
 *
 * Recent builds are weighted more heavily so the estimate tracks trends
 * (e.g. a job that has been getting faster recently will have a lower estimate).
 */
public class ExecutionTimeEstimator {

    private static final Logger LOGGER =
            Logger.getLogger(ExecutionTimeEstimator.class.getName());

    /**
     * Recency weights for Weighted Moving Average.
     * Index 0 = most recent build, index 4 = oldest of the five.
     * Must sum to 1.0.
     */
    private static final double[] RECENCY_WEIGHTS = {0.40, 0.30, 0.15, 0.10, 0.05};

    private static final int MIN_OWN_BUILDS = 3;

    private final BuildHistoryAnalyzer historyAnalyzer;

    /**
     * Memoizes estimate(jobName) for the duration of a single scoring pass.
     * The dispatcher rescores every queued job on each maintenance cycle, and
     * the same job names recur repeatedly (once per item being scored, plus
     * once per peer when normalising execution-time scores). Build-history
     * lookups don't change mid-cycle, so caching here removes that repeat
     * work without affecting the result. Call clearCache() when the queue
     * snapshot changes (i.e. at the start of the next pass).
     */
    private final Map<String, Double> cache = new ConcurrentHashMap<>();

    public ExecutionTimeEstimator(BuildHistoryAnalyzer historyAnalyzer) {
        this.historyAnalyzer = historyAnalyzer;
    }

    /** Clears the per-pass estimate cache. Call at the start of a new scoring pass. */
    public void clearCache() {
        cache.clear();
    }

    /**
     * Returns estimated execution time in seconds for the given job.
     */
    public double estimate(String jobName) {
        Double cached = cache.get(jobName);
        if (cached != null) {
            return cached;
        }
        double estimate = computeEstimate(jobName);
        cache.put(jobName, estimate);
        return estimate;
    }

    private double computeEstimate(String jobName) {

        // --- Strategy 1: own history ---
        List<Double> ownHistory = historyAnalyzer.getRecentSuccessfulDurations(jobName);
        if (ownHistory.size() >= MIN_OWN_BUILDS) {
            double estimate = weightedMovingAverage(ownHistory);
            LOGGER.fine(String.format(
                    "Estimator[%s]: own history (%d builds) → %.1fs",
                    jobName, ownHistory.size(), estimate));
            return estimate;
        }

        // --- Strategy 2: similar jobs ---
        List<String> similarJobs = historyAnalyzer.findSimilarJobNames(jobName);
        if (!similarJobs.isEmpty()) {
            double sum = 0;
            int count = 0;
            for (String similar : similarJobs) {
                List<Double> hist = historyAnalyzer.getRecentSuccessfulDurations(similar);
                if (!hist.isEmpty()) {
                    sum += hist.get(0); // most recent build of the similar job
                    count++;
                }
            }
            if (count > 0) {
                double estimate = sum / count;
                LOGGER.fine(String.format(
                        "Estimator[%s]: similar jobs (%d found) → %.1fs",
                        jobName, count, estimate));
                return estimate;
            }
        }

        // --- Strategy 3: global average ---
        double globalAvg = historyAnalyzer.getGlobalAverageDuration();
        LOGGER.fine(String.format(
                "Estimator[%s]: global average fallback → %.1fs", jobName, globalAvg));
        return globalAvg;
    }

    /**
     * Weighted Moving Average over up to 5 most-recent durations.
     *
     * Example with durations [60, 55, 70, 65, 50] (newest first):
     *   WMA = (60×0.40) + (55×0.30) + (70×0.15) + (65×0.10) + (50×0.05)
     *       = 24 + 16.5 + 10.5 + 6.5 + 2.5 = 60.0 seconds
     */
    private double weightedMovingAverage(List<Double> durations) {
        int limit = Math.min(durations.size(), RECENCY_WEIGHTS.length);
        double weightedSum = 0;
        double totalWeight  = 0;

        for (int i = 0; i < limit; i++) {
            weightedSum  += durations.get(i) * RECENCY_WEIGHTS[i];
            totalWeight  += RECENCY_WEIGHTS[i];
        }

        return weightedSum / totalWeight;
    }
}
