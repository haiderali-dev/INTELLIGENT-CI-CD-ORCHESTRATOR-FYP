package io.jenkins.plugins.queueoptimizer.metrics;

import hudson.Extension;
import hudson.model.Result;
import hudson.model.Run;
import hudson.model.TaskListener;
import hudson.model.listeners.RunListener;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.estimation.RecordedLabelAction;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;

/**
 * Records build starts and completions: result, duration, and for Pipeline runs the queue waiting
 * time attributable to their node blocks.
 *
 * <p>The Pipeline case is the reason this class is not a two-line listener. A Pipeline run's own
 * start time says almost nothing, because the run begins as a flyweight task the moment it is
 * scheduled. What a user actually waits for is the node blocks. BUILD_PROMPT 4.8.4 therefore asks
 * for the first node block's wait and the sum of all node-block waits as separate figures, and both
 * are computed here from the events the queue recorder already captured.
 */
@Extension
public class RunMetricsRecorder extends RunListener<Run<?, ?>> {

    @Override
    public void onStarted(Run<?, ?> run, TaskListener listener) {
        MetricsPublisher.get()
                .record(MetricEvent.of(MetricEvent.Kind.BUILD_STARTED)
                        .with("jobName", run.getParent().getFullName())
                        .with("buildNumber", run.getNumber())
                        .with("jobType", run.getParent().getClass().getSimpleName())
                        .with(
                                "level",
                                JobPriorityProperty.levelOf(run.getParent()).name())
                        .with("agentLabel", labelOf(run))
                        .with("startTimeMillis", run.getStartTimeInMillis())
                        .with("optimizerEnabled", OptimizerConfiguration.get().isOptimizerEnabled()));
    }

    @Override
    public void onCompleted(Run<?, ?> run, TaskListener listener) {
        Result result = run.getResult();
        NodeBlockWaits waits = nodeBlockWaits(run.getParent().getFullName(), run.getNumber());

        MetricsPublisher.get()
                .record(MetricEvent.of(MetricEvent.Kind.BUILD_COMPLETED)
                        .with("jobName", run.getParent().getFullName())
                        .with("buildNumber", run.getNumber())
                        .with("jobType", run.getParent().getClass().getSimpleName())
                        .with(
                                "level",
                                JobPriorityProperty.levelOf(run.getParent()).name())
                        .with("result", result == null ? "UNKNOWN" : result.toString())
                        .with("durationMillis", run.getDuration())
                        .with("startTimeMillis", run.getStartTimeInMillis())
                        .with("agentLabel", labelOf(run))
                        // Both figures, reported separately, per BUILD_PROMPT 4.8.4.
                        .with("firstNodeBlockWaitMillis", waits.first)
                        .with("totalNodeBlockWaitMillis", waits.total)
                        .with("nodeBlockCount", waits.count)
                        .with("optimizerEnabled", OptimizerConfiguration.get().isOptimizerEnabled()));
    }

    private static String labelOf(Run<?, ?> run) {
        RecordedLabelAction action = run.getAction(RecordedLabelAction.class);
        return action == null ? "" : action.getLabel();
    }

    /**
     * Sums the node-block waits this run accumulated, from the recorder's recent events.
     *
     * <p>Reads the in-memory ring rather than keeping separate state, so there is one source of
     * truth for a wait and no chance of the two disagreeing. For a freestyle job this finds the
     * single queue event for the job itself, which is exactly the wait that matters there.
     */
    private static NodeBlockWaits nodeBlockWaits(String jobName, int buildNumber) {
        long total = 0;
        long first = -1;
        int count = 0;

        for (MetricEvent event : MetricsPublisher.get().getRecent(Integer.MAX_VALUE)) {
            if (event.getKind() != MetricEvent.Kind.QUEUE_LEFT) {
                continue;
            }
            Object name = event.getFields().get("jobName");
            Object wait = event.getFields().get("waitMillis");
            if (!jobName.equals(name) || !(wait instanceof Number waitMillis)) {
                continue;
            }
            if (Boolean.TRUE.equals(event.getFields().get("cancelled"))) {
                continue;
            }
            // Only executor-consuming items are a real wait; a flyweight task never queued for one.
            if (Boolean.FALSE.equals(event.getFields().get("consumesExecutor"))) {
                continue;
            }
            long millis = waitMillis.longValue();
            if (first < 0) {
                first = millis;
            }
            total += millis;
            count++;
        }
        return new NodeBlockWaits(Math.max(0, first), total, count);
    }

    private record NodeBlockWaits(long first, long total, int count) {}
}
