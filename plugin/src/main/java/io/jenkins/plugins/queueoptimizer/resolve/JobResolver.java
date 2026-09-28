package io.jenkins.plugins.queueoptimizer.resolve;

import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.model.Job;
import hudson.model.Queue;
import java.util.Optional;

/**
 * Finds the {@link Job} behind a queue item, for every job type the optimizer covers.
 *
 * <p>This class is the single fix for Milestone 2's largest functional gap. Its dispatcher began
 * with {@code if (!(item.task instanceof AbstractProject)) return null;}, so every Pipeline job
 * bypassed the optimizer entirely while the plugin advertised Pipeline support.
 *
 * <p>Both branches below are load bearing, which is not obvious and was measured rather than
 * assumed (see {@code QueueShapeProbeIT} and {@code docs/decisions.md} D-014). A Pipeline job
 * passes through the queue twice:
 *
 * <ol>
 *   <li>First as the {@code WorkflowJob} itself, a flyweight task waiting to start the run. Here
 *       {@code item.task} <em>is</em> a {@code Job}, and branch one returns it.
 *   <li>Then, once the script reaches a {@code node} block, as a {@code PlaceholderTask}. Here it
 *       is not, and branch two walks {@code getOwnerTask()} to reach the job, which the probe
 *       measured at exactly one hop.
 * </ol>
 *
 * <p>Freestyle and Maven jobs only ever take branch one.
 */
public final class JobResolver {

    /**
     * How far to follow {@code getOwnerTask()}. One hop is enough for a Pipeline node block on
     * the current baseline; five leaves room for nesting without ever looping indefinitely on a
     * task graph that unexpectedly cycles.
     */
    private static final int MAX_OWNER_HOPS = 5;

    private JobResolver() {}

    /**
     * Resolves the job that owns a queue item.
     *
     * @param item any queue item
     * @return the owning job, or empty when the item belongs to no job, in which case the caller
     *     must leave the item's position alone rather than guess
     */
    @NonNull
    public static Optional<Job<?, ?>> resolve(@NonNull Queue.Item item) {
        return resolveTask(item.task);
    }

    /** As {@link #resolve(Queue.Item)}, for a bare task. */
    @NonNull
    public static Optional<Job<?, ?>> resolveTask(Queue.Task task) {
        Queue.Task cursor = task;
        for (int hop = 0; hop < MAX_OWNER_HOPS; hop++) {
            if (cursor instanceof Job<?, ?> job) {
                return Optional.of(job);
            }
            Queue.Task owner = cursor.getOwnerTask();
            if (owner == null || owner == cursor) {
                // getOwnerTask() returns self at the top of the chain.
                break;
            }
            cursor = owner;
        }
        return Optional.empty();
    }

    /**
     * True when this item is a Pipeline node block rather than a whole job.
     *
     * <p>The distinction decides gating. Blocking a node block of a run already in progress would
     * hold an executor hostage mid-build for a dependency the run has already satisfied, so
     * {@code DependencyGate} gates whole jobs only.
     */
    public static boolean isNodeBlock(@NonNull Queue.Item item) {
        return !(item.task instanceof Job);
    }

    /**
     * True when this item consumes an executor slot.
     *
     * <p>Flyweight tasks run on a one-off executor and never compete for a slot, so ordering them
     * is meaningless. A Pipeline job's first queue appearance is one of these.
     */
    public static boolean consumesExecutor(@NonNull Queue.Item item) {
        return !(item.task instanceof Queue.FlyweightTask);
    }

    /** The full name of the owning job, or the task's display name when nothing resolves. */
    @NonNull
    public static String describe(@NonNull Queue.Item item) {
        return resolve(item).map(Job::getFullName).orElseGet(() -> item.task.getDisplayName());
    }
}
