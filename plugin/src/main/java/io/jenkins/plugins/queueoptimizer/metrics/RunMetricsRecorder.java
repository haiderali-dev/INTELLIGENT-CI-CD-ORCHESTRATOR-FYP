package io.jenkins.plugins.queueoptimizer.metrics;

import hudson.Extension;
import hudson.model.Result;
import hudson.model.Run;
import hudson.model.TaskListener;
import hudson.model.listeners.RunListener;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.estimation.RecordedLabelAction;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;

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
        NodeBlockWaits waits = nodeBlockWaits(
                MetricsPublisher.get().getRecent(Integer.MAX_VALUE),
                run.getParent().getFullName(),
                run.getQueueId(),
                run.getStartTimeInMillis());

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
     * Sums the executor waits of one build, from the recorder's recent events.
     *
     * <p>Reads the in-memory ring rather than keeping separate state, so there is one source of
     * truth for a wait and no chance of the two disagreeing. A wait belongs to this build when it is
     * the build's own queue item ({@code queueId}, which is how a freestyle job waits) or a node
     * block that entered the queue after the build started (which is how a Pipeline waits). The
     * ring also holds earlier builds of the same job, and matching on the job name alone summed
     * their waits into this one's (DF-45).
     */
    static NodeBlockWaits nodeBlockWaits(List<MetricEvent> events, String jobName, long queueId, long startMillis) {
        long total = 0;
        long first = -1;
        int count = 0;

        for (MetricEvent event : events) {
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
            if (!belongsToBuild(event, queueId, startMillis)) {
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

    private static boolean belongsToBuild(MetricEvent event, long queueId, long startMillis) {
        Object itemId = event.getFields().get("itemId");
        if (itemId instanceof Number id && id.longValue() == queueId) {
            return true;
        }
        Object since = event.getFields().get("inQueueSince");
        return Boolean.TRUE.equals(event.getFields().get("isNodeBlock"))
                && since instanceof Number queued
                && queued.longValue() >= startMillis;
    }

    /** One build's executor waits: the first one, their sum, and how many there were. */
    record NodeBlockWaits(long first, long total, int count) {}
}
