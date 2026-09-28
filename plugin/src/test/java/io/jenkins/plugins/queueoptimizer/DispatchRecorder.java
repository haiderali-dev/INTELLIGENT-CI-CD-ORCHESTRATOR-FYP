package io.jenkins.plugins.queueoptimizer;

import hudson.ExtensionList;
import hudson.model.Job;
import hudson.model.Queue;
import hudson.model.queue.QueueListener;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.jvnet.hudson.test.JenkinsRule;

/**
 * Records the order in which the queue actually hands work to executors.
 *
 * <p>This exists because the obvious measurement is wrong. Comparing
 * {@code Run#getStartTimeInMillis()} works for freestyle jobs but not for Pipeline: a Pipeline
 * run starts as a flyweight task the moment it is scheduled, long before its {@code node} block
 * reaches the front of the queue. Ranking Pipeline jobs by run start time therefore measures
 * when each script began executing, which no scheduler decision influences, and would keep
 * failing however correct the sorter became.
 *
 * <p>What the sorter actually controls is the order in which items <em>leave</em> the queue onto
 * an executor. {@link QueueListener#onLeft} reports exactly that, for freestyle tasks and
 * Pipeline placeholder tasks alike, so it is the ground truth every ordering assertion uses.
 *
 * <p>Cancelled items are ignored: they left the queue without ever being dispatched.
 */
public final class DispatchRecorder extends QueueListener {

    private final List<String> dispatched = new CopyOnWriteArrayList<>();

    private DispatchRecorder() {}

    /**
     * Registers a recorder on this Jenkins instance.
     *
     * <p>Call before scheduling anything that matters. The JenkinsRule instance is discarded
     * after each test, so the registration does not leak between tests.
     */
    public static DispatchRecorder attach(JenkinsRule rule) {
        DispatchRecorder recorder = new DispatchRecorder();
        ExtensionList.lookup(QueueListener.class).add(0, recorder);
        return recorder;
    }

    @Override
    public void onLeft(Queue.LeftItem item) {
        if (item.isCancelled()) {
            // Left the queue without ever being dispatched.
            return;
        }
        if (item.task instanceof Queue.FlyweightTask) {
            // Flyweight tasks run on a one-off executor and never compete for an executor slot,
            // so they are not a scheduling decision and must not appear in the order.
            //
            // This matters concretely: a Pipeline job leaves the queue twice, first as its own
            // flyweight task and again as the node block's placeholder. Counting both made the
            // recorded order [pl-low, pl-high, pl-high, pl-low], where the first two entries are
            // merely the order the runs were scheduled in. Comparing those would measure
            // scheduling latency instead of the sorter's decision.
            return;
        }
        resolveJobName(item).ifPresent(dispatched::add);
    }

    /** Job names in the order their work was dispatched to an executor, oldest first. */
    public List<String> order() {
        return List.copyOf(dispatched);
    }

    /** The position at which a job was first dispatched, or -1. */
    public int positionOf(String jobName) {
        return dispatched.indexOf(jobName);
    }

    /**
     * Resolves a queue item to the job that owns it.
     *
     * <p>Deliberately mirrors what {@code JobResolver} will do, rather than calling it: these
     * tests establish the Jenkins behaviour that {@code JobResolver} is built on, so depending
     * on it here would make the proof circular.
     */
    private static java.util.Optional<String> resolveJobName(Queue.Item item) {
        Queue.Task task = item.task;
        for (int hop = 0; hop < 5; hop++) {
            if (task instanceof Job<?, ?> job) {
                return java.util.Optional.of(job.getFullName());
            }
            Queue.Task owner = task.getOwnerTask();
            if (owner == task) {
                break;
            }
            task = owner;
        }
        return java.util.Optional.empty();
    }
}
