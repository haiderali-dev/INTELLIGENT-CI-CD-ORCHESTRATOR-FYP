package io.jenkins.plugins.queueoptimizer.model;

/**
 * Holds execution metrics for a single completed build.
 * Used by BuildHistoryAnalyzer to store and pass historical data.
 */
public class BuildMetrics {

    private final String jobName;
    private final long buildNumber;
    private final double durationSeconds;
    private final String result;       // SUCCESS, FAILURE, UNSTABLE, etc.
    private final long startTimeMillis;

    public BuildMetrics(String jobName, long buildNumber,
                        double durationSeconds, String result,
                        long startTimeMillis) {
        this.jobName = jobName;
        this.buildNumber = buildNumber;
        this.durationSeconds = durationSeconds;
        this.result = result;
        this.startTimeMillis = startTimeMillis;
    }

    public String getJobName()            { return jobName; }
    public long getBuildNumber()          { return buildNumber; }
    public double getDurationSeconds()    { return durationSeconds; }
    public String getResult()             { return result; }
    public long getStartTimeMillis()      { return startTimeMillis; }

    public boolean isSuccess() {
        return "SUCCESS".equalsIgnoreCase(result);
    }

    @Override
    public String toString() {
        return String.format("BuildMetrics[job=%s, build=#%d, duration=%.1fs, result=%s]",
                jobName, buildNumber, durationSeconds, result);
    }
}
