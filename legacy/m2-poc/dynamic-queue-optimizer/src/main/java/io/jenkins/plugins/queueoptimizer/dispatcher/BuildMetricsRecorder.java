package io.jenkins.plugins.queueoptimizer.dispatcher;

import hudson.Extension;
import hudson.model.Result;
import hudson.model.Run;
import hudson.model.TaskListener;
import hudson.model.listeners.RunListener;

import java.util.logging.Logger;

/**
 * Listens for build-completion events and records execution metrics.
 *
 * Jenkins calls onCompleted() after every build finishes (success or failure).
 * We use this hook to:
 *   1. Remove the finished job from the heap (cleanup).
 *   2. Print a structured metrics line to the build log — this line is what
 *      you copy into your experiment spreadsheet for Phase 1 vs Phase 2 comparison.
 *
 * The @Extension annotation registers this listener automatically.
 */
@Extension
public class BuildMetricsRecorder extends RunListener<Run<?, ?>> {

    private static final Logger LOGGER =
            Logger.getLogger(BuildMetricsRecorder.class.getName());

    @Override
    public void onCompleted(Run<?, ?> run, TaskListener listener) {
        String jobName        = run.getParent().getFullName();
        long   durationMs     = run.getDuration();
        double durationSec    = durationMs / 1000.0;
        long   startTimeMs    = run.getStartTimeInMillis();
        String result         = run.getResult() != null ? run.getResult().toString() : "UNKNOWN";

        // Clean up heap entry
        DynamicQueueDispatcher.getHeap().remove(run.getQueueId());

        // Structured log line — easy to parse into CSV for your experiments
        String metricsLine = String.format(
                "[METRICS] job=%s | build=#%d | start=%d | durationMs=%d | durationSec=%.1f | result=%s",
                jobName,
                run.getNumber(),
                startTimeMs,
                durationMs,
                durationSec,
                result);

        LOGGER.info(metricsLine);

        // Also print to the build console log so it's visible in Jenkins UI
        listener.getLogger().println();
        listener.getLogger().println("╔══ Dynamic Queue Optimizer — Build Metrics ══════════════");
        listener.getLogger().println("║  Job:      " + jobName);
        listener.getLogger().println("║  Build:    #" + run.getNumber());
        listener.getLogger().println("║  Duration: " + String.format("%.1f", durationSec) + " seconds");
        listener.getLogger().println("║  Result:   " + result);
        listener.getLogger().println("╚══════════════════════════════════════════════════════════");
        listener.getLogger().println();
    }

    @Override
    public void onStarted(Run<?, ?> run, TaskListener listener) {
        String jobName = run.getParent().getFullName();
        long   startMs = run.getStartTimeInMillis();

        listener.getLogger().println("[DynamicQueueOptimizer] Job started: "
                + jobName + " at " + startMs + " ms");
        LOGGER.info("Build started: " + jobName + " at " + startMs + " ms");
    }
}
