package io.jenkins.plugins.queueoptimizer.metrics;

import hudson.Extension;
import hudson.model.Job;
import hudson.model.Queue;
import hudson.model.queue.QueueListener;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.resolve.JobResolver;
import io.jenkins.plugins.queueoptimizer.sorter.DynamicQueueSorter;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * Records when items enter and leave the queue, which is where every waiting-time KPI comes from.
 *
 * <p>Records node blocks as well as whole jobs, deliberately. A Pipeline run's waiting time is the
 * sum of its node blocks' waits, not the time before the run object appeared, so a recorder that
 * skipped placeholders would report Pipeline queue waits as near zero and make the whole Pipeline
 * arm of the experiment meaningless.
 *
 * <p>Runs even when the optimizer is disabled. That is what makes the experiment's observe-only
 * baseline a fair comparison: both arms are measured by exactly the same code on the same
 * installation, rather than by two separate Jenkins homes as in Milestone 2.
 */
@Extension
public class QueueMetricsRecorder extends QueueListener {

    /** Enqueue time per item id, so the wait can be computed when the item leaves. */
    private final ConcurrentMap<Long, Long> enteredAt = new ConcurrentHashMap<>();

    @Override
    public void onEnterWaiting(Queue.WaitingItem item) {
        enteredAt.put(item.getId(), System.currentTimeMillis());
        publisher().record(baseEvent(MetricEvent.Kind.QUEUE_ENTERED, item));
    }

    @Override
    public void onLeft(Queue.LeftItem item) {
        Long entered = enteredAt.remove(item.getId());
        long now = System.currentTimeMillis();
        long waitMillis = entered == null ? Math.max(0, now - item.getInQueueSince()) : now - entered;

        MetricEvent event = baseEvent(MetricEvent.Kind.QUEUE_LEFT, item)
                .with("waitMillis", waitMillis)
                .with("cancelled", item.isCancelled());

        // The score the sorter assigned, so the backend can report why an item ranked where it did
        // rather than only how long it waited.
        DynamicQueueSorter.getHeap()
                .get(item.getId())
                .ifPresent(scored -> event.with("score", round(scored.score()))
                        .with("baseScore", round(scored.baseScore()))
                        .with("agingBonus", round(scored.agingBonus()))
                        .with("urgencyFactor", round(scored.urgencyFactor()))
                        .with("dependencyFactor", round(scored.dependencyFactor()))
                        .with("executionTimeFactor", round(scored.executionTimeFactor()))
                        .with("groupId", scored.groupId())
                        .with("groupSize", scored.groupSize()));

        publisher().record(event);
    }

    /** Fields common to every queue event. */
    private static MetricEvent baseEvent(MetricEvent.Kind kind, Queue.Item item) {
        Optional<Job<?, ?>> job = JobResolver.resolve(item);
        return MetricEvent.of(kind)
                .with("itemId", item.getId())
                .with("jobName", job.map(Job::getFullName).orElse(item.task.getDisplayName()))
                .with("jobType", job.map(j -> j.getClass().getSimpleName()).orElse("unknown"))
                .with("isNodeBlock", JobResolver.isNodeBlock(item))
                .with("consumesExecutor", JobResolver.consumesExecutor(item))
                .with(
                        "level",
                        job.map(j -> JobPriorityProperty.levelOf(j).name()).orElse("MEDIUM"))
                .with("inQueueSince", item.getInQueueSince())
                .with("optimizerEnabled", OptimizerConfiguration.get().isOptimizerEnabled());
    }

    /** Six decimal places: enough to reconstruct a score, short enough to keep events small. */
    private static double round(double value) {
        return Math.round(value * 1_000_000d) / 1_000_000d;
    }

    private static MetricsPublisher publisher() {
        return MetricsPublisher.get();
    }
}
