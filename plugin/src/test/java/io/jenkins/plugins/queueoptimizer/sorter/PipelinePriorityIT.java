package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.assertAllDispatchedBefore;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilNodeBlocksBuildable;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.Job;
import hudson.model.Queue;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import java.util.Optional;
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition;
import org.jenkinsci.plugins.workflow.job.WorkflowJob;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Proves the assumption the whole Pipeline story rests on: that the optimizer can see, and
 * reorder, Pipeline work in the queue.
 *
 * <p>This is not a formality. Milestone 2's dispatcher opened with
 * {@code if (!(item.task instanceof AbstractProject)) return null;}, so every Pipeline job
 * bypassed the optimizer completely and nobody noticed, because there was no test. The plugin
 * shipped advertising Pipeline support it did not have.
 *
 * <p>The mechanism is subtle enough to be worth stating precisely, because the obvious summary
 * is wrong. A Pipeline job passes through the queue <em>twice</em>, in two different shapes,
 * as measured by {@link io.jenkins.plugins.queueoptimizer.QueueShapeProbeIT}:
 *
 * <ol>
 *   <li>First as the {@code WorkflowJob} itself, a flyweight task waiting to start the run.
 *       Here {@code item.task instanceof Job} is <em>true</em>. This window is short, but it is
 *       real, and a test that samples the queue during it measures the wrong thing.
 *   <li>Then, once the script reaches a {@code node} block, as a {@code PlaceholderTask}, whose
 *       {@code task} is not a {@code Job} at all. The job is exactly one {@code getOwnerTask()}
 *       hop away.
 * </ol>
 *
 * <p>So {@code JobResolver} needs both branches, and any code that only tests
 * {@code item.task instanceof Job} misses every node block.
 *
 * <p>Written before the sorter exists, so it is expected to fail on arrival order until T2.9.
 */
@WithJenkins
class PipelinePriorityIT {

    private static final String SCRIPT = "node { echo 'work' }";

    @Test
    @DisplayName("a HIGH Pipeline job takes the executor before a LOW one, on one executor")
    void highPipelineRunsBeforeLowPipeline(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        // Nothing may start until every item is queued, so the sorter sees them together.
        j.jenkins.setNumExecutors(0);

        // Submitted worst-first: under FIFO this is exactly the wrong order.
        WorkflowJob low = pipeline(j, "pl-low", "LOW");
        WorkflowJob high = pipeline(j, "pl-high", "HIGH");

        low.scheduleBuild2(0);
        high.scheduleBuild2(0);

        // Each run reaches its `node` block and parks a placeholder task in the queue.
        // Waiting on the shape, not just the count: for a moment each WorkflowJob is itself
        // queued as a flyweight task, and sampling then would test the wrong thing entirely.
        waitUntilNodeBlocksBuildable(j, 2);

        assertTrue(
                queueHoldsOnlyPlaceholders(j),
                "expected the queue to hold PlaceholderTasks rather than the jobs themselves; "
                        + "if these are Jobs, the assumption behind JobResolver is wrong");

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("pl-low", "pl-high"));

        assertAllDispatchedBefore(
                dispatches,
                List.of("pl-high"),
                List.of("pl-low"),
                "The Pipeline queue is not being ordered by priority.");
    }

    @Test
    @DisplayName("Pipeline placeholder tasks resolve to their job without throwing")
    void placeholderTasksResolveToTheirJob(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);
        WorkflowJob job = pipeline(j, "pl-resolve", "HIGH");
        job.scheduleBuild2(0);
        waitUntilNodeBlocksBuildable(j, 1);

        Queue.Item item = j.jenkins.getQueue().getBuildableItems().stream()
                .filter(i -> !(i.task instanceof Job))
                .findFirst()
                .orElseThrow(() -> new AssertionError("no Pipeline node block in the queue"));

        assertFalse(
                item.task instanceof Job,
                "a Pipeline node block should enter the queue as a placeholder, not as the job");

        Optional<Job<?, ?>> resolved = walkOwnerTaskToJob(item);
        assertTrue(resolved.isPresent(), "getOwnerTask() did not lead to a Job");
        assertEquals("pl-resolve", resolved.get().getFullName());

        // The property must be readable from the resolved job; this is what scoring needs.
        JobPriorityProperty property = resolved.get().getProperty(JobPriorityProperty.class);
        assertTrue(property != null, "the priority property was not readable from the resolved job");
        assertEquals("HIGH", property.getLevel());

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("pl-resolve"));
    }

    @Test
    @DisplayName("priority ordering holds across a mix of freestyle and Pipeline jobs")
    void highPipelineOutranksLowFreestyle(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        var freestyleLow = j.createFreeStyleProject("fs-low");
        freestyleLow.addProperty(new JobPriorityProperty("LOW", ""));
        WorkflowJob pipelineHigh = pipeline(j, "pl-high-mixed", "HIGH");

        freestyleLow.scheduleBuild2(0);
        pipelineHigh.scheduleBuild2(0);
        // The Pipeline contributes a node block; the freestyle job queues directly.
        waitUntilNodeBlocksBuildable(j, 1);
        waitUntilBuildable(j, 2);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("fs-low", "pl-high-mixed"));

        assertAllDispatchedBefore(
                dispatches,
                List.of("pl-high-mixed"),
                List.of("fs-low"),
                "One scoring formula must rank freestyle and Pipeline jobs against each other.");
    }

    /**
     * Walks {@code getOwnerTask()} to the owning job, the way {@code JobResolver} will.
     *
     * <p>Duplicated here on purpose. This test exists to prove the Jenkins behaviour itself, so
     * it must not depend on the production class whose correctness it is establishing.
     */
    private static Optional<Job<?, ?>> walkOwnerTaskToJob(Queue.Item item) {
        Queue.Task task = item.task;
        for (int hop = 0; hop < 5; hop++) {
            if (task instanceof Job<?, ?> job) {
                return Optional.of(job);
            }
            Queue.Task owner = task.getOwnerTask();
            if (owner == task) {
                break;
            }
            task = owner;
        }
        return Optional.empty();
    }

    private static boolean queueHoldsOnlyPlaceholders(JenkinsRule j) {
        return j.jenkins.getQueue().getBuildableItems().stream().noneMatch(i -> i.task instanceof Job);
    }

    private static WorkflowJob pipeline(JenkinsRule j, String name, String level) throws Exception {
        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, name);
        job.setDefinition(new CpsFlowDefinition(SCRIPT, true));
        job.addProperty(new JobPriorityProperty(level, ""));
        return job;
    }
}
