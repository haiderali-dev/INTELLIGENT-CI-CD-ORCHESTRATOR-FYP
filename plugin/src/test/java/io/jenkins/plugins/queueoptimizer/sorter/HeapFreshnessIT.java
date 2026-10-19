package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.FreeStyleProject;
import hudson.model.Queue;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.metrics.MetricEvent;
import io.jenkins.plugins.queueoptimizer.metrics.MetricsPublisher;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.SleepBuilder;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * The heap holds exactly the items buildable at the last pass, scored, whatever their number.
 *
 * <p>Found in T6.6: the sorter returned early below two buildable items, so a lone waiting job was
 * never scored, and the heap kept whatever an earlier pass left there. The queue page then showed a
 * lone job as "not scored by the optimizer", or with an aging bonus older than its wait, and the
 * run card's score came from the same stale heap.
 */
@WithJenkins
class HeapFreshnessIT {

    @Test
    @DisplayName("a lone buildable job is scored")
    void loneJobIsScored(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        FreeStyleProject project = schedule(j, "lone-high", "HIGH");
        waitUntilBuildable(j, 1);

        j.jenkins.getQueue().maintain();

        Queue.Item item = j.jenkins.getQueue().getItems(project).get(0);
        assertTrue(
                DynamicQueueSorter.getHeap().get(item.getId()).isPresent(),
                "the only buildable item must be scored, not skipped for being alone");
        assertEquals(1, DynamicQueueSorter.getHeap().size());

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("lone-high"));
    }

    @Test
    @DisplayName("the heap empties when the queue does")
    void heapEmptiesWithTheQueue(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        schedule(j, "drained-1", "LOW");
        schedule(j, "drained-2", "HIGH");
        waitUntilBuildable(j, 2);
        j.jenkins.getQueue().maintain();
        assertEquals(2, DynamicQueueSorter.getHeap().size());

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("drained-1", "drained-2"));
        j.jenkins.getQueue().maintain();

        assertEquals(
                0,
                DynamicQueueSorter.getHeap().size(),
                "items that left must not stay ranked after the queue is empty");
    }

    @Test
    @DisplayName("the baseline arm leaves nothing in the heap")
    void baselineLeavesTheHeapEmpty(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        schedule(j, "arm-1", "LOW");
        schedule(j, "arm-2", "HIGH");
        waitUntilBuildable(j, 2);
        j.jenkins.getQueue().maintain();
        assertEquals(2, DynamicQueueSorter.getHeap().size(), "scored while the optimizer is on");

        OptimizerConfiguration.get().setOptimizerEnabled(false);
        j.jenkins.getQueue().maintain();

        assertEquals(
                0,
                DynamicQueueSorter.getHeap().size(),
                "with the optimizer off, nothing is ranked: no score from before it was switched off");

        OptimizerConfiguration.get().setOptimizerEnabled(true);
        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("arm-1", "arm-2"));
    }

    @Test
    @DisplayName("a queue-left event keeps its score after a later pass rebuilt the heap without it")
    void queueLeftKeepsItsScore(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        FreeStyleProject first = schedule(j, "left-high", "HIGH");
        first.getBuildersList().add(new SleepBuilder(1000));
        schedule(j, "left-low", "LOW");
        waitUntilBuildable(j, 2);
        j.jenkins.getQueue().maintain();

        // One executor: the HIGH job leaves first, and every pass after that rebuilds the heap with
        // the LOW job alone, so the HIGH job's score is no longer in the heap when it is recorded.
        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("left-high", "left-low"));

        for (String name : List.of("left-high", "left-low")) {
            MetricEvent left = MetricsPublisher.get().getRecent(Integer.MAX_VALUE).stream()
                    .filter(event -> event.getKind() == MetricEvent.Kind.QUEUE_LEFT)
                    .filter(event -> name.equals(event.getFields().get("jobName")))
                    .findFirst()
                    .orElseThrow(() -> new AssertionError("no QUEUE_LEFT event for " + name));
            assertTrue(
                    left.getFields().containsKey("score"),
                    name + " left the queue without the score it was dispatched on: " + left.getFields());
        }
    }

    @Test
    @DisplayName("an item's score outlives the heap until the item leaves, and is taken only once")
    void scoreOutlivesTheHeap(JenkinsRule j) throws Exception {
        // The mechanism directly, with no race to win: a pass that finds nothing buildable empties
        // the heap, as it must, but the score of an item already handed to an executor is still
        // there for its QUEUE_LEFT event.
        j.jenkins.setNumExecutors(0);
        FreeStyleProject project = schedule(j, "outlives", "HIGH");
        schedule(j, "outlives-other", "LOW");
        waitUntilBuildable(j, 2);
        j.jenkins.getQueue().maintain();
        long itemId = j.jenkins.getQueue().getItems(project).get(0).getId();

        DynamicQueueSorter.getInstance().sortBuildableItems(new java.util.ArrayList<>());

        assertEquals(0, DynamicQueueSorter.getHeap().size(), "a pass with nothing buildable empties the heap");
        assertTrue(DynamicQueueSorter.takeLastScore(itemId).isPresent(), "the score is kept for the exit event");
        assertTrue(DynamicQueueSorter.takeLastScore(itemId).isEmpty(), "and taken once, so nothing accumulates");

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("outlives", "outlives-other"));
    }

    private static FreeStyleProject schedule(JenkinsRule j, String name, String level) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject(name);
        project.addProperty(new JobPriorityProperty(level, ""));
        project.scheduleBuild2(0);
        return project;
    }
}
