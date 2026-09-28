package io.jenkins.plugins.queueoptimizer.estimation;

import hudson.model.Job;
import hudson.model.Result;
import hudson.model.Run;
import io.jenkins.plugins.queueoptimizer.model.BuildMetrics;
import jenkins.model.Jenkins;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * Fetches historical build data from Jenkins internal storage.
 *
 * Jenkins keeps every build's metadata (duration, result, timestamps) in memory
 * and on disk. This class reads that data via the Jenkins Java API — no database
 * or external tool is required.
 */
public class BuildHistoryAnalyzer {

    private static final Logger LOGGER =
            Logger.getLogger(BuildHistoryAnalyzer.class.getName());

    private static final int MAX_BUILDS_TO_FETCH = 10;

    /**
     * Returns the durations (in seconds) of recent SUCCESSFUL builds for
     * the given job, ordered from newest to oldest.
     *
     * Only successful builds are used because failed/aborted builds have
     * artificially short or misleading durations.
     */
    public List<Double> getRecentSuccessfulDurations(String jobName) {
        List<Double> durations = new ArrayList<>();

        Job<?, ?> job = Jenkins.get().getItemByFullName(jobName, Job.class);
        if (job == null) {
            LOGGER.fine("BuildHistoryAnalyzer: job not found in Jenkins: " + jobName);
            return durations;
        }

        int count = 0;
        for (Run<?, ?> build : job.getBuilds()) {
            if (count >= MAX_BUILDS_TO_FETCH) break;

            if (Result.SUCCESS.equals(build.getResult()) && build.getDuration() > 0) {
                double seconds = build.getDuration() / 1000.0;
                durations.add(seconds);
                count++;
            }
        }

        LOGGER.fine(String.format(
                "BuildHistoryAnalyzer: found %d successful builds for '%s'",
                durations.size(), jobName));
        return durations;
    }

    /**
     * Returns full BuildMetrics objects for the most recent builds.
     * Useful when you need result status alongside duration.
     */
    public List<BuildMetrics> getRecentBuildMetrics(String jobName) {
        List<BuildMetrics> metrics = new ArrayList<>();

        Job<?, ?> job = Jenkins.get().getItemByFullName(jobName, Job.class);
        if (job == null) return metrics;

        int count = 0;
        for (Run<?, ?> build : job.getBuilds()) {
            if (count >= MAX_BUILDS_TO_FETCH) break;
            if (build.getDuration() > 0 && build.getResult() != null) {
                metrics.add(new BuildMetrics(
                        jobName,
                        build.getNumber(),
                        build.getDuration() / 1000.0,
                        build.getResult().toString(),
                        build.getStartTimeInMillis()
                ));
                count++;
            }
        }
        return metrics;
    }

    /**
     * Computes the average duration across ALL jobs in this Jenkins instance.
     * Used as the last-resort fallback when a job has zero build history.
     */
    public double getGlobalAverageDuration() {
        List<Double> allDurations = new ArrayList<>();

        for (Job<?, ?> job : Jenkins.get().getAllItems(Job.class)) {
            Run<?, ?> last = job.getLastSuccessfulBuild();
            if (last != null && last.getDuration() > 0) {
                allDurations.add(last.getDuration() / 1000.0);
            }
        }

        if (allDurations.isEmpty()) {
            LOGGER.fine("BuildHistoryAnalyzer: no global history found, defaulting to 60s");
            return 60.0;
        }

        double avg = allDurations.stream()
                .mapToDouble(Double::doubleValue)
                .average()
                .orElse(60.0);

        LOGGER.fine(String.format("BuildHistoryAnalyzer: global average duration = %.1fs", avg));
        return avg;
    }

    /**
     * Finds other jobs whose names share common tokens with the target job.
     * Token splitting uses hyphens, underscores, and spaces as delimiters.
     *
     * Example: "build-backend-api" shares tokens with "test-backend-service"
     * → both contain "backend" → considered similar.
     */
    public List<String> findSimilarJobNames(String targetJobName) {
        List<String> similar = new ArrayList<>();
        String[] targetTokens = targetJobName.toLowerCase().split("[-_\\s]+");

        for (Job<?, ?> job : Jenkins.get().getAllItems(Job.class)) {
            String candidateName = job.getFullName();
            if (candidateName.equals(targetJobName)) continue;

            String[] candidateTokens = candidateName.toLowerCase().split("[-_\\s]+");
            int commonTokens = countCommonTokens(targetTokens, candidateTokens);
            int minLen = Math.min(targetTokens.length, candidateTokens.length);

            if (minLen > 0 && commonTokens >= Math.ceil(minLen / 2.0)) {
                similar.add(candidateName);
            }
        }

        LOGGER.fine(String.format(
                "BuildHistoryAnalyzer: found %d similar jobs for '%s'",
                similar.size(), targetJobName));
        return similar;
    }

    private int countCommonTokens(String[] a, String[] b) {
        int count = 0;
        for (String ta : a) {
            for (String tb : b) {
                if (ta.equals(tb)) count++;
            }
        }
        return count;
    }
}
