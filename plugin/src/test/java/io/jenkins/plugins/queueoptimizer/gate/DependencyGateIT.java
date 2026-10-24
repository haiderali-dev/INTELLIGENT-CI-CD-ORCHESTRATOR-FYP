package io.jenkins.plugins.queueoptimizer.gate;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.assertAllDispatchedBefore;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilNodeBlocksBuildable;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import hudson.Launcher;
import hudson.model.AbstractBuild;
import hudson.model.BuildListener;
import hudson.model.FreeStyleProject;
import hudson.model.Job;
import hudson.model.Queue;
import hudson.model.queue.CauseOfBlockage;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition;
import org.jenkinsci.plugins.workflow.job.WorkflowJob;
import org.jenkinsci.plugins.workflow.job.WorkflowRun;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.SleepBuilder;
import org.jvnet.hudson.test.TestBuilder;
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

    @Test
    @DisplayName("a Pipeline queued before its upstream still waits for it, at its node block")
    void pipelineQueuedBeforeItsUpstreamWaitsAtItsNodeBlock(JenkinsRule j) throws Exception {
        // Phase 7's matrix, pipeline-30 on three executors, all three repetitions. The fixed
        // LOW, MEDIUM, HIGH order queues release-notes-generator (MEDIUM) a second before its
        // upstream smoke-test-production (HIGH). When the downstream's flyweight passed the gate,
        // nothing it depends on was queued or building, so its run started. Its node block, which
        // the gate never holds, then took the next free executor while the upstream sat in the
        // queue held for its own producers, and the downstream ran a minute before the upstream.
        //
        // The same states here, one at a time, so nothing races:
        //   1. one executor, which the producer takes and keeps until the test releases it;
        //   2. the downstream, a Pipeline, is queued: nothing it depends on is queued or
        //      building, so its run starts and its node block waits for an executor;
        //   3. its upstream is queued, and the gate holds it, since its producer is building;
        //   4. a second executor appears while the upstream is still held.
        // The downstream's node block must not take that executor: its upstream is queued.
        j.jenkins.setNumExecutors(1);
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        HeldUntilReleased.latch = new CountDownLatch(1);

        FreeStyleProject producer = j.createFreeStyleProject("gate-producer");
        producer.addProperty(new JobPriorityProperty("LOW", ""));
        producer.getBuildersList().add(new HeldUntilReleased());

        FreeStyleProject upstream = j.createFreeStyleProject("gate-upstream");
        upstream.addProperty(new JobPriorityProperty("HIGH", "gate-producer"));

        WorkflowJob downstream = j.jenkins.createProject(WorkflowJob.class, "gate-pl-downstream");
        downstream.setDefinition(new CpsFlowDefinition("node { echo 'work' }", true));
        downstream.addProperty(new JobPriorityProperty("MEDIUM", "gate-upstream"));

        try {
            producer.scheduleBuild2(0);
            waitUntilBuilding(j, "gate-producer");

            downstream.scheduleBuild2(0);
            waitUntilNodeBlocksBuildable(j, 1);

            upstream.scheduleBuild2(0);
            waitForBlockage(j, "gate-upstream");

            j.jenkins.setNumExecutors(2);
            CauseOfBlockage held = waitForNodeBlockHeldOrDispatched(j, dispatches, "gate-pl-downstream");
            DependencyGate.UpstreamRunning running = assertInstanceOf(
                    DependencyGate.UpstreamRunning.class,
                    held,
                    "the downstream's node block should wait for its queued upstream, as a freestyle "
                            + "job's queue item does");
            org.junit.jupiter.api.Assertions.assertEquals("gate-upstream", running.getUpstreamName());
        } finally {
            HeldUntilReleased.latch.countDown();
        }

        waitUntilAllComplete(j, List.of("gate-producer", "gate-upstream", "gate-pl-downstream"));
        assertAllDispatchedBefore(
                dispatches,
                List.of("gate-upstream"),
                List.of("gate-pl-downstream"),
                "A Pipeline queued before its upstream must still run after it.");
    }

    @Test
    @DisplayName("a Pipeline already doing its work is not held at its next node block")
    void workingPipelineIsNotHeldAtItsNextNodeBlock(JenkinsRule j) throws Exception {
        // The other half of DF-48's fix. Once a node block of a run has had an executor, the run's
        // later node blocks are never held, as no node block was before. The upstream is queued
        // only after the downstream's first node block has run, so a gate that held every node
        // block would stop the run halfway, with nothing left to protect.
        assertFinishesWhileItsUpstreamIsHeld(
                j, "node { echo 'first' }\nsleep(time: 5, unit: 'SECONDS')\nnode { echo 'second' }", 2);
    }

    @Test
    @DisplayName("a nested node block is not held while its outer block keeps an executor")
    void nestedNodeBlockIsNotHeld(JenkinsRule j) throws Exception {
        // The deadlock the node-block rule exists to prevent. The outer block keeps an executor
        // while the inner one waits, so an inner block held for its upstream would keep that
        // executor from all other work. Three executors: the producer, the outer block, the inner.
        assertFinishesWhileItsUpstreamIsHeld(j, "node { sleep(time: 5, unit: 'SECONDS'); node { echo 'inner' } }", 3);
    }

    /**
     * Runs a Pipeline whose upstream is queued, and held for its producer, only once the Pipeline's
     * first node block has an executor. Asserts that the Pipeline still finishes while its upstream
     * waits.
     */
    private static void assertFinishesWhileItsUpstreamIsHeld(JenkinsRule j, String script, int executors)
            throws Exception {
        j.jenkins.setNumExecutors(executors);
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        HeldUntilReleased.latch = new CountDownLatch(1);

        FreeStyleProject producer = j.createFreeStyleProject("work-producer");
        producer.getBuildersList().add(new HeldUntilReleased());

        FreeStyleProject upstream = j.createFreeStyleProject("work-upstream");
        upstream.addProperty(new JobPriorityProperty("HIGH", "work-producer"));

        WorkflowJob downstream = j.jenkins.createProject(WorkflowJob.class, "work-pl-downstream");
        downstream.setDefinition(new CpsFlowDefinition(script, true));
        downstream.addProperty(new JobPriorityProperty("MEDIUM", "work-upstream"));

        try {
            producer.scheduleBuild2(0);
            waitUntilBuilding(j, "work-producer");

            downstream.scheduleBuild2(0);
            waitUntilDispatched(j, dispatches, "work-pl-downstream");

            upstream.scheduleBuild2(0);
            waitForBlockage(j, "work-upstream");
            org.junit.jupiter.api.Assertions.assertEquals(
                    1L,
                    dispatches.order().stream()
                            .filter("work-pl-downstream"::equals)
                            .count(),
                    "the upstream must be queued before the downstream's next node block is, or this "
                            + "test proves nothing");

            WorkflowRun run = downstream.getLastBuild();
            assertNotNull(run);
            long deadline = System.currentTimeMillis() + 60_000;
            while (run.isBuilding() && System.currentTimeMillis() < deadline) {
                j.jenkins.getQueue().maintain();
                Thread.sleep(50);
            }
            assertTrue(
                    !run.isBuilding(),
                    "the downstream's later node block was held mid-build; observed dispatch order: "
                            + dispatches.order());
            j.assertBuildStatusSuccess(run);
            assertTrue(upstream.getLastBuild() == null, "the upstream should still be held for its producer");
        } finally {
            HeldUntilReleased.latch.countDown();
        }

        waitUntilAllComplete(j, List.of("work-producer", "work-upstream", "work-pl-downstream"));
    }

    /** Waits until the named job's work has been dispatched to an executor at least once. */
    private static void waitUntilDispatched(JenkinsRule j, DispatchRecorder dispatches, String jobName)
            throws Exception {
        long deadline = System.currentTimeMillis() + 60_000;
        while (System.currentTimeMillis() < deadline) {
            j.jenkins.getQueue().maintain();
            if (dispatches.positionOf(jobName) >= 0) {
                return;
            }
            Thread.sleep(50);
        }
        fail("timed out waiting for " + jobName + "'s work to be dispatched");
    }

    /**
     * Waits until the named Pipeline's node block either reports a cause of blockage, which it
     * returns, or is dispatched to an executor, which fails the test at once.
     */
    private static CauseOfBlockage waitForNodeBlockHeldOrDispatched(
            JenkinsRule j, DispatchRecorder dispatches, String jobName) throws Exception {
        long deadline = System.currentTimeMillis() + 60_000;
        while (System.currentTimeMillis() < deadline) {
            j.jenkins.getQueue().maintain();
            if (dispatches.positionOf(jobName) >= 0) {
                fail(jobName + "'s node block took an executor while its upstream was still queued; "
                        + "observed dispatch order: " + dispatches.order());
            }
            for (Queue.Item item : j.jenkins.getQueue().getItems()) {
                boolean ownNodeBlock = !(item.task instanceof Job)
                        && item.task.getOwnerTask() instanceof Job<?, ?> owner
                        && owner.getFullName().equals(jobName);
                if (ownNodeBlock && item.getCauseOfBlockage() instanceof DependencyGate.UpstreamRunning held) {
                    return held;
                }
            }
            Thread.sleep(50);
        }
        fail("timed out waiting for " + jobName + "'s node block to be held or dispatched");
        return null;
    }

    /** Keeps a freestyle build running until the test counts the latch down. */
    private static final class HeldUntilReleased extends TestBuilder {

        static volatile CountDownLatch latch = new CountDownLatch(1);

        @Override
        public boolean perform(AbstractBuild<?, ?> build, Launcher launcher, BuildListener listener)
                throws InterruptedException {
            return latch.await(90, TimeUnit.SECONDS);
        }
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
