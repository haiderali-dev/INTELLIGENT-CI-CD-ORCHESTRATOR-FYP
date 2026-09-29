package io.jenkins.plugins.queueoptimizer.gate;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.assertAllDispatchedBefore;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import hudson.model.FreeStyleProject;
import hudson.model.Queue;
import hudson.model.queue.CauseOfBlockage;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.SleepBuilder;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Required by BUILD_PROMPT 4.3.10: a downstream job waits while its upstream is queued or building.
 *
 * <p>The interesting case, and the one asserted here, is a downstream job that the <em>sorter</em>
 * ranks first. The gate has to win that argument: a HIGH job whose producer is still running must
 * wait regardless of its score, or it builds against an artifact that does not exist yet. Ordering
 * and gating are separate concerns, and this is where they meet.
 *
 * <p>Two executors throughout, so nothing here can pass merely because no executor was free.
 */
@WithJenkins
class DependencyGateIT {

    @Test
    @DisplayName("a HIGH downstream job waits for its LOW upstream, despite outranking it")
    void downstreamWaitsForRunningUpstream(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(2);
        DispatchRecorder dispatches = DispatchRecorder.attach(j);

        FreeStyleProject upstream = j.createFreeStyleProject("fs-upstream");
        upstream.addProperty(new JobPriorityProperty("LOW", ""));
        upstream.getBuildersList().add(new SleepBuilder(4000));

        FreeStyleProject downstream = j.createFreeStyleProject("fs-downstream");
        downstream.addProperty(new JobPriorityProperty("HIGH", "fs-upstream"));

        upstream.scheduleBuild2(0);
        waitUntilBuilding(j, "fs-upstream");

        // Queued while the upstream is mid-build. The sorter would put this first.
        downstream.scheduleBuild2(0);

        CauseOfBlockage blockage = waitForBlockage(j, "fs-downstream");
        DependencyGate.UpstreamRunning upstreamRunning = assertInstanceOf(
                DependencyGate.UpstreamRunning.class,
                blockage,
                "the gate should be the thing holding this item, with a reason a user can read");
        org.junit.jupiter.api.Assertions.assertEquals("fs-upstream", upstreamRunning.getUpstreamName());
        assertTrue(
                upstreamRunning.getShortDescription().contains("fs-upstream"),
                "the reason must name the upstream job: " + upstreamRunning.getShortDescription());

        waitUntilAllComplete(j, List.of("fs-upstream", "fs-downstream"));

        assertAllDispatchedBefore(
                dispatches,
                List.of("fs-upstream"),
                List.of("fs-downstream"),
                "A HIGH downstream job must still wait for its producer. If it ran first, the gate "
                        + "lost to the sorter and the build would consume an artifact that does not "
                        + "exist yet.");
    }

    @Test
    @DisplayName("a downstream job waits while its upstream is merely queued, not yet building")
    void downstreamWaitsForQueuedUpstream(JenkinsRule j) throws Exception {
        // Zero executors, so the upstream cannot start. The gate must still hold the downstream:
        // "queued" counts as unfinished just as much as "building" does.
        j.jenkins.setNumExecutors(0);

        FreeStyleProject upstream = j.createFreeStyleProject("q-upstream");
        FreeStyleProject downstream = j.createFreeStyleProject("q-downstream");
        downstream.addProperty(new JobPriorityProperty("HIGH", "q-upstream"));

        upstream.scheduleBuild2(0);
        downstream.scheduleBuild2(0);

        CauseOfBlockage blockage = waitForBlockage(j, "q-downstream");
        DependencyGate.UpstreamRunning running = assertInstanceOf(DependencyGate.UpstreamRunning.class, blockage);
        org.junit.jupiter.api.Assertions.assertEquals("queued", running.getUpstreamState());

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("q-upstream", "q-downstream"));
    }

    @Test
    @DisplayName("a whole chain runs in order, not just one link")
    void threeJobChainRunsInOrder(JenkinsRule j) throws Exception {
        // The shape the Freestyle Assistant produces: build then test then deploy, each naming the
        // previous in dependsOn. Three executors are free, so only the gate enforces the order.
        j.jenkins.setNumExecutors(3);
        DispatchRecorder dispatches = DispatchRecorder.attach(j);

        FreeStyleProject build = j.createFreeStyleProject("fs-svc-build");
        build.addProperty(new JobPriorityProperty("MEDIUM", ""));
        build.getBuildersList().add(new SleepBuilder(2000));

        FreeStyleProject test = j.createFreeStyleProject("fs-svc-test");
        test.addProperty(new JobPriorityProperty("MEDIUM", "fs-svc-build"));
        test.getBuildersList().add(new SleepBuilder(2000));

        FreeStyleProject deploy = j.createFreeStyleProject("fs-svc-deploy");
        deploy.addProperty(new JobPriorityProperty("HIGH", "fs-svc-test"));

        build.scheduleBuild2(0);
        test.scheduleBuild2(0);
        deploy.scheduleBuild2(0);

        waitUntilAllComplete(j, List.of("fs-svc-build", "fs-svc-test", "fs-svc-deploy"));

        assertAllDispatchedBefore(dispatches, List.of("fs-svc-build"), List.of("fs-svc-test"), "build before test");
        assertAllDispatchedBefore(dispatches, List.of("fs-svc-test"), List.of("fs-svc-deploy"), "test before deploy");
    }

    @Test
    @DisplayName("an upstream that merely failed does not block its downstream")
    void failedUpstreamDoesNotBlock(JenkinsRule j) throws Exception {
        // Whether a chain stops after a failure is the backend's decision, made by not triggering
        // the next job. If the gate decided it, the item would sit queued forever with no way for
        // a user to find out why.
        j.jenkins.setNumExecutors(2);

        FreeStyleProject upstream = j.createFreeStyleProject("failing-upstream");
        upstream.getBuildersList().add(new org.jvnet.hudson.test.FailureBuilder());
        j.buildAndAssertStatus(hudson.model.Result.FAILURE, upstream);

        FreeStyleProject downstream = j.createFreeStyleProject("after-failure");
        downstream.addProperty(new JobPriorityProperty("MEDIUM", "failing-upstream"));

        // Completes rather than hanging: the assertion is that this call returns at all.
        j.buildAndAssertSuccess(downstream);
    }

    @Test
    @DisplayName("a finished upstream stops blocking")
    void finishedUpstreamDoesNotBlock(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(2);

        FreeStyleProject upstream = j.createFreeStyleProject("done-upstream");
        j.buildAndAssertSuccess(upstream);

        FreeStyleProject downstream = j.createFreeStyleProject("after-done");
        downstream.addProperty(new JobPriorityProperty("MEDIUM", "done-upstream"));

        j.buildAndAssertSuccess(downstream);
    }

    @Test
    @DisplayName("a self-dependency in a hand-edited config does not deadlock the job")
    void selfDependencyDoesNotDeadlock(JenkinsRule j) throws Exception {
        // Form validation rejects this, but config.xml can be written by hand or by a script.
        // Blocking the job on itself would hang it forever.
        j.jenkins.setNumExecutors(2);

        FreeStyleProject project = j.createFreeStyleProject("self-dep");
        project.addProperty(new JobPriorityProperty("MEDIUM", "self-dep"));

        j.buildAndAssertSuccess(project);
    }

    private static void waitUntilBuilding(JenkinsRule j, String jobName) throws Exception {
        long deadline = System.currentTimeMillis() + 60_000;
        while (System.currentTimeMillis() < deadline) {
            FreeStyleProject project = j.jenkins.getItemByFullName(jobName, FreeStyleProject.class);
            if (project != null && project.isBuilding()) {
                return;
            }
            Thread.sleep(50);
        }
        fail("timed out waiting for " + jobName + " to start building");
    }

    /** Waits for the named job's queue item to report a cause of blockage. */
    private static CauseOfBlockage waitForBlockage(JenkinsRule j, String jobName) throws Exception {
        long deadline = System.currentTimeMillis() + 60_000;
        while (System.currentTimeMillis() < deadline) {
            j.jenkins.getQueue().maintain();
            for (Queue.Item item : j.jenkins.getQueue().getItems()) {
                if (item.task.getName().equals(jobName)) {
                    CauseOfBlockage blockage = item.getCauseOfBlockage();
                    if (blockage != null) {
                        return blockage;
                    }
                }
            }
            Thread.sleep(50);
        }
        fail("timed out waiting for " + jobName + " to report a cause of blockage");
        return null;
    }

    @Test
    @DisplayName("the blockage carries the blocked job's own name too")
    void blockageNamesBothJobs(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);

        j.createFreeStyleProject("both-upstream").scheduleBuild2(0);
        FreeStyleProject downstream = j.createFreeStyleProject("both-downstream");
        downstream.addProperty(new JobPriorityProperty("MEDIUM", "both-upstream"));
        downstream.scheduleBuild2(0);

        DependencyGate.UpstreamRunning running =
                assertInstanceOf(DependencyGate.UpstreamRunning.class, waitForBlockage(j, "both-downstream"));
        assertNotNull(running.getJobName());
        org.junit.jupiter.api.Assertions.assertEquals("both-downstream", running.getJobName());

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("both-upstream", "both-downstream"));
    }
}
