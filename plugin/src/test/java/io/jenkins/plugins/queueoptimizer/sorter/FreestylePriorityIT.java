package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.assertAllDispatchedBefore;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static org.junit.jupiter.api.Assertions.assertEquals;

import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Required by BUILD_PROMPT 4.3.10: HIGH runs before LOW on one executor.
 *
 * <p>The baseline capability, and the one Milestone 2 did deliver. Kept as its own test rather than
 * folded into {@link MultiExecutorIT} because it is the single-executor case, which is the only
 * configuration Milestone 2 ever measured, so a regression here would invalidate the comparison
 * against its published numbers.
 */
@WithJenkins
class FreestylePriorityIT {

    @Test
    @DisplayName("a HIGH freestyle job runs before a LOW one on a single executor")
    void highRunsBeforeLow(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        // LOW submitted first, so FIFO and priority order disagree.
        schedule(j, "fsp-low", "LOW");
        schedule(j, "fsp-high", "HIGH");
        waitUntilBuildable(j, 2);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("fsp-low", "fsp-high"));

        assertAllDispatchedBefore(dispatches, List.of("fsp-high"), List.of("fsp-low"), "HIGH must outrank LOW.");
    }

    @Test
    @DisplayName("all three bands drain in priority order")
    void bandsDrainInOrder(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        // Submitted LOW, MEDIUM, HIGH, which is the experiment's arrival pattern: the order that
        // makes FIFO look worst and is therefore the order the M2 results were measured under.
        schedule(j, "band-low", "LOW");
        schedule(j, "band-medium", "MEDIUM");
        schedule(j, "band-high", "HIGH");
        waitUntilBuildable(j, 3);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("band-low", "band-medium", "band-high"));

        assertEquals(
                List.of("band-high", "band-medium", "band-low"),
                dispatches.order(),
                "one executor makes the drain order fully determined, so the whole permutation "
                        + "can be asserted rather than a partial ordering");
    }

    @Test
    @DisplayName("a job with no priority property is treated as MEDIUM")
    void unconfiguredJobIsMedium(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        // No property at all: must schedule as MEDIUM rather than being rejected or sorted last.
        j.createFreeStyleProject("bare-job").scheduleBuild2(0);
        schedule(j, "explicit-high", "HIGH");
        schedule(j, "explicit-low", "LOW");
        waitUntilBuildable(j, 3);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("bare-job", "explicit-high", "explicit-low"));

        assertEquals(
                List.of("explicit-high", "bare-job", "explicit-low"),
                dispatches.order(),
                "an unconfigured job belongs between HIGH and LOW, not at either end");
    }

    @Test
    @DisplayName("jobs of equal priority keep their arrival order")
    void equalPriorityIsFifo(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        List<String> submitted = List.of("tie-a", "tie-b", "tie-c");
        for (String name : submitted) {
            schedule(j, name, "MEDIUM");
        }
        waitUntilBuildable(j, 3);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, submitted);

        assertEquals(
                submitted,
                dispatches.order(),
                "equal scores must fall back to arrival order, or the scheduler is not "
                        + "deterministic and nobody can reproduce a run");
    }

    @Test
    @DisplayName("a second build of the same job queues and runs without disturbing the ranking")
    void repeatedBuildsOfOneJob(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        FreeStyleProject low = j.createFreeStyleProject("repeat-low");
        low.addProperty(new JobPriorityProperty("LOW", ""));
        // Two builds of the same LOW job, plus one HIGH job. The HIGH job must still go first even
        // though the LOW job occupies more of the queue.
        low.scheduleBuild2(0);
        schedule(j, "repeat-high", "HIGH");
        waitUntilBuildable(j, 2);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("repeat-low", "repeat-high"));

        assertAllDispatchedBefore(
                dispatches, List.of("repeat-high"), List.of("repeat-low"), "queue volume must not outweigh priority");
    }

    private static void schedule(JenkinsRule j, String name, String level) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject(name);
        project.addProperty(new JobPriorityProperty(level, ""));
        project.scheduleBuild2(0);
    }
}
