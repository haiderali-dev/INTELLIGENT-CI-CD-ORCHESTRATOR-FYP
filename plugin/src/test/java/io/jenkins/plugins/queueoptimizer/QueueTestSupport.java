package io.jenkins.plugins.queueoptimizer;

import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import hudson.model.Job;
import hudson.model.Queue;
import hudson.model.Run;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Predicate;
import java.util.stream.Collectors;
import jenkins.model.Jenkins;
import org.jvnet.hudson.test.JenkinsRule;

/**
 * Helpers for the queue integration tests.
 *
 * <p>Every ordering test here follows the same shape, because it is the only way to observe
 * scheduling decisions without racing them:
 *
 * <ol>
 *   <li>Set the executor count to zero, so nothing can start.
 *   <li>Submit the jobs. They pile up in the queue as buildable items, all visible to the
 *       sorter at once, exactly as they would under a burst of real submissions.
 *   <li>Wait until every expected item is actually buildable.
 *   <li>Raise the executor count. Jenkins now drains the queue in whatever order the sorter
 *       decided.
 *   <li>Compare the resulting build start times.
 * </ol>
 *
 * <p>The alternative, occupying the executor with a long sleeping job, makes the assertions
 * depend on that sleep being long enough, which is how flaky scheduling tests are written.
 */
public final class QueueTestSupport {

    /** How long to wait for a queue or build state before declaring the test broken. */
    private static final long TIMEOUT_MILLIS = 90_000;

    private static final long POLL_MILLIS = 100;

    private QueueTestSupport() {}

    /**
     * Blocks until at least {@code count} items are buildable, or fails the test.
     *
     * <p>Buildable is the state that matters: the item is ready to run and is only waiting for
     * a free executor. That is the list {@code QueueSorter} is handed.
     */
    public static void waitUntilBuildable(JenkinsRule rule, int count) throws InterruptedException {
        waitUntilBuildable(rule, count, item -> true, String.valueOf(count) + " buildable items");
    }

    /**
     * Blocks until at least {@code count} buildable items are Pipeline node blocks.
     *
     * <p>Necessary because a Pipeline job passes through the queue <em>twice</em>, and only the
     * second appearance is the one worth testing:
     *
     * <ol>
     *   <li>Briefly as the {@code WorkflowJob} itself, a flyweight task waiting to start the
     *       run. Here {@code item.task instanceof Job} is <em>true</em>.
     *   <li>Then, once the run reaches its {@code node} block, as a {@code PlaceholderTask}.
     *       Here {@code item.task instanceof Job} is <em>false</em> and the job is one
     *       {@code getOwnerTask()} hop away.
     * </ol>
     *
     * <p>Simply counting buildable items races that transition and can sample the first window,
     * which makes a test either spuriously pass or fail for the wrong reason. Measured with
     * {@link QueueShapeProbeIT}; recorded in {@code docs/decisions.md} D-014.
     */
    public static void waitUntilNodeBlocksBuildable(JenkinsRule rule, int count)
            throws InterruptedException {
        waitUntilBuildable(
                rule,
                count,
                item -> !(item.task instanceof Job),
                count + " Pipeline node blocks (placeholder tasks)");
    }

    private static void waitUntilBuildable(
            JenkinsRule rule, int count, Predicate<Queue.Item> shape, String what)
            throws InterruptedException {
        long deadline = System.currentTimeMillis() + TIMEOUT_MILLIS;
        while (System.currentTimeMillis() < deadline) {
            Queue queue = rule.jenkins.getQueue();
            queue.maintain();
            long matching = queue.getBuildableItems().stream().filter(shape).count();
            if (matching >= count) {
                return;
            }
            Thread.sleep(POLL_MILLIS);
        }
        fail("timed out waiting for " + what + "; queue held: " + describeQueue(rule.jenkins));
    }

    /** Blocks until every named job has at least one completed build, or fails the test. */
    public static void waitUntilAllComplete(JenkinsRule rule, List<String> jobNames)
            throws InterruptedException {
        long deadline = System.currentTimeMillis() + TIMEOUT_MILLIS;
        while (System.currentTimeMillis() < deadline) {
            List<String> pending = new ArrayList<>();
            for (String name : jobNames) {
                Job<?, ?> job = rule.jenkins.getItemByFullName(name, Job.class);
                Run<?, ?> last = job == null ? null : job.getLastBuild();
                if (last == null || last.isBuilding()) {
                    pending.add(name);
                }
            }
            if (pending.isEmpty()) {
                return;
            }
            Thread.sleep(POLL_MILLIS);
        }
        fail("timed out waiting for builds to finish; queue held: " + describeQueue(rule.jenkins));
    }

    /**
     * Asserts that every job in {@code earlier} was dispatched before every job in
     * {@code later}.
     *
     * <p>Dispatch order, from {@link DispatchRecorder}, is the only valid ground truth here.
     * Run start times are not: a Pipeline run starts as a flyweight task the moment it is
     * scheduled, well before its {@code node} block reaches the front of the queue, so ranking
     * Pipeline jobs by start time measures something no scheduling decision affects.
     *
     * <p>Deliberately weaker than asserting one exact permutation. With several executors the
     * order within a band is genuinely non-deterministic, and a test that pinned it would fail
     * for reasons that do not matter.
     */
    public static void assertAllDispatchedBefore(
            DispatchRecorder recorder, List<String> earlier, List<String> later, String because) {
        List<String> order = recorder.order();

        List<String> missing = new ArrayList<>();
        for (String name : concat(earlier, later)) {
            if (!order.contains(name)) {
                missing.add(name);
            }
        }
        if (!missing.isEmpty()) {
            fail(because + "\n  these jobs were never dispatched: " + missing
                    + "\n  observed dispatch order: " + order);
        }

        int lastOfEarlier = earlier.stream().mapToInt(recorder::positionOf).max().orElseThrow();
        int firstOfLater = later.stream().mapToInt(recorder::positionOf).min().orElseThrow();

        assertTrue(
                lastOfEarlier < firstOfLater,
                because
                        + "\n  expected every one of " + earlier + " to be dispatched before any of "
                        + later
                        + "\n  observed dispatch order: " + order
                        + "\n  last of the earlier group at index " + lastOfEarlier
                        + ", first of the later group at index " + firstOfLater);
    }

    private static List<String> concat(List<String> a, List<String> b) {
        List<String> all = new ArrayList<>(a);
        all.addAll(b);
        return all;
    }

    private static String describeQueue(Jenkins jenkins) {
        // Queue.getItems() returns an array, not a collection.
        return java.util.Arrays.stream(jenkins.getQueue().getItems())
                .map(item -> item.task.getDisplayName() + "[" + item.getCauseOfBlockage() + "]")
                .collect(Collectors.joining(", ", "{", "}"));
    }
}
