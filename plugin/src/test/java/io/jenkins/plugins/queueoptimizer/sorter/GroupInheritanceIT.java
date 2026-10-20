package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.assertAllDispatchedBefore;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

import hudson.model.FreeStyleProject;
import hudson.model.Queue;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.gate.DependencyGate;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.scoring.ScoredJob;
import java.util.ArrayList;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Group inheritance in a live queue, where the dependency gate holds the consumer.
 *
 * <p>The report's Appendix C scores a producer and its consumer together: the group takes its best
 * member's score, so a LOW build whose output a more urgent job is waiting for runs early instead of
 * delaying that job. In a real queue the consumer is never buildable while its producer waits,
 * because {@link DependencyGate} holds it back, and Jenkins hands the sorter buildable items only.
 * Grouped over that list alone, the producer was always a group of one: D was 0, nothing was
 * inherited, and the LOW producer sat behind every MEDIUM job while the HIGH job it unblocks
 * waited too. Found while planning the testing chapter's white-box tests (D-067).
 */
@WithJenkins
class GroupInheritanceIT {

    private static final List<String> MEDIUM_WORK = List.of("gi-medium-1", "gi-medium-2", "gi-medium-3");

    /**
     * Queues a LOW producer, its HIGH consumer and three unrelated MEDIUM jobs on zero executors,
     * and waits until the gate holds the consumer and the other four are buildable.
     */
    private static void queueTheChainAndOtherWork(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);

        FreeStyleProject producer = j.createFreeStyleProject("gi-build-api");
        producer.addProperty(new JobPriorityProperty("LOW", ""));
        FreeStyleProject consumer = j.createFreeStyleProject("gi-deploy-api");
        consumer.addProperty(new JobPriorityProperty("HIGH", "gi-build-api"));
        List<FreeStyleProject> medium = new ArrayList<>();
        for (String name : MEDIUM_WORK) {
            FreeStyleProject job = j.createFreeStyleProject(name);
            job.addProperty(new JobPriorityProperty("MEDIUM", ""));
            medium.add(job);
        }

        producer.scheduleBuild2(0);
        consumer.scheduleBuild2(0);
        for (FreeStyleProject job : medium) {
            job.scheduleBuild2(0);
        }

        waitUntilBuildable(j, 4);
        waitUntilHeld(j, "gi-deploy-api");
        // One more pass, so the sorter runs with the held consumer in the queue's snapshot.
        j.jenkins.getQueue().maintain();
    }

    @Test
    @DisplayName("a LOW producer whose HIGH consumer is held by the gate runs before MEDIUM work")
    void producerOfAHeldUrgentJobRunsFirst(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        queueTheChainAndOtherWork(j);

        j.jenkins.setNumExecutors(1);
        List<String> all = new ArrayList<>(MEDIUM_WORK);
        all.add("gi-build-api");
        all.add("gi-deploy-api");
        waitUntilAllComplete(j, all);

        assertAllDispatchedBefore(
                dispatches,
                List.of("gi-build-api"),
                MEDIUM_WORK,
                "The LOW producer must inherit the score of the HIGH job waiting for it (report "
                        + "Appendix C). Ranked on its own it sits behind every MEDIUM job, and the HIGH "
                        + "deployment waits for all of them too.");
        assertAllDispatchedBefore(
                dispatches,
                List.of("gi-deploy-api"),
                MEDIUM_WORK,
                "Once its producer has built, the HIGH consumer is next.");
    }

    @Test
    @DisplayName("the held consumer lifts its producer's score, and the ranking shows it as inherited")
    void theRankingShowsTheInheritedScore(JenkinsRule j) throws Exception {
        queueTheChainAndOtherWork(j);

        ScoredJob producer = scoreOf("gi-build-api");
        ScoredJob medium = scoreOf("gi-medium-1");

        assertEquals(1.0, producer.dependencyFactor(), 1e-9, "the producer heads a group of two");
        assertTrue(producer.inheritedGroupScore(), "its score comes from the job it unblocks");
        assertTrue(
                producer.score() > medium.score(),
                "producer " + producer.score() + " must outrank MEDIUM " + medium.score());
        // The held consumer is grouped, never ranked: it cannot run, so it is not in the heap.
        assertTrue(
                DynamicQueueSorter.getHeap().getAllOrdered().stream()
                        .noneMatch(job -> job.jobName().equals("gi-deploy-api")),
                "a held item must not appear among the ranked, runnable work");
    }

    @Test
    @DisplayName("a consumer queued after its producer was ranked lifts the producer at once")
    void aLateConsumerLiftsAWaitingProducer(JenkinsRule j) throws Exception {
        // The everyday shape: a build is already waiting when the deployment that needs it is
        // requested. The buildable items do not change when the consumer arrives, because the gate
        // holds it, so the sorter's cache must see the held item, or it keeps the producer's old
        // score until something buildable changes or the minute turns.
        j.jenkins.setNumExecutors(0);

        FreeStyleProject producer = j.createFreeStyleProject("gi-late-build");
        producer.addProperty(new JobPriorityProperty("LOW", ""));
        FreeStyleProject consumer = j.createFreeStyleProject("gi-late-deploy");
        consumer.addProperty(new JobPriorityProperty("HIGH", "gi-late-build"));
        FreeStyleProject medium = j.createFreeStyleProject("gi-late-medium");
        medium.addProperty(new JobPriorityProperty("MEDIUM", ""));

        producer.scheduleBuild2(0);
        medium.scheduleBuild2(0);
        waitUntilBuildable(j, 2);
        j.jenkins.getQueue().maintain();
        assertTrue(
                scoreOf("gi-late-build").score() < scoreOf("gi-late-medium").score(),
                "on its own the LOW build ranks below MEDIUM work");

        consumer.scheduleBuild2(0);
        waitUntilHeld(j, "gi-late-deploy");
        j.jenkins.getQueue().maintain();

        ScoredJob lifted = scoreOf("gi-late-build");
        assertTrue(lifted.inheritedGroupScore(), "the waiting deployment lends the build its score");
        assertTrue(
                lifted.score() > scoreOf("gi-late-medium").score(),
                "the build now outranks MEDIUM work: "
                        + DynamicQueueSorter.getHeap().getAllOrdered());
    }

    @Test
    @DisplayName("a job the gate releases is ranked in that same pass, not left behind on cached scores")
    void aReleasedJobIsRankedAtOnce(JenkinsRule j) throws Exception {
        // Both HIGH, so the upstream runs first whatever the groups. The question is the next
        // pass: the consumer moves from held to buildable while the set of queued items stays the
        // same. Keyed on that set alone, the sorter served the previous pass's scores, which had
        // none for the consumer, and the MEDIUM job took the executor first.
        j.jenkins.setNumExecutors(0);
        DispatchRecorder dispatches = DispatchRecorder.attach(j);

        FreeStyleProject upstream = j.createFreeStyleProject("gi-fast-upstream");
        upstream.addProperty(new JobPriorityProperty("HIGH", ""));
        FreeStyleProject consumer = j.createFreeStyleProject("gi-fast-consumer");
        consumer.addProperty(new JobPriorityProperty("HIGH", "gi-fast-upstream"));
        FreeStyleProject other = j.createFreeStyleProject("gi-other-medium");
        other.addProperty(new JobPriorityProperty("MEDIUM", ""));

        upstream.scheduleBuild2(0);
        consumer.scheduleBuild2(0);
        other.scheduleBuild2(0);
        waitUntilBuildable(j, 2);
        waitUntilHeld(j, "gi-fast-consumer");

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("gi-fast-upstream", "gi-fast-consumer", "gi-other-medium"));

        assertAllDispatchedBefore(
                dispatches,
                List.of("gi-fast-consumer"),
                List.of("gi-other-medium"),
                "Once its upstream has finished, the HIGH consumer outranks the MEDIUM job and must "
                        + "take the executor, in the pass that releases it.");
    }

    private static ScoredJob scoreOf(String jobName) {
        return DynamicQueueSorter.getHeap().getAllOrdered().stream()
                .filter(job -> job.jobName().equals(jobName))
                .findFirst()
                .orElseThrow(() -> new AssertionError(jobName + " is not ranked; heap: "
                        + DynamicQueueSorter.getHeap().getAllOrdered()));
    }

    /** Waits until the gate is the thing holding the named job. */
    private static void waitUntilHeld(JenkinsRule j, String jobName) throws Exception {
        long deadline = System.currentTimeMillis() + 60_000;
        while (System.currentTimeMillis() < deadline) {
            j.jenkins.getQueue().maintain();
            for (Queue.Item item : j.jenkins.getQueue().getItems()) {
                if (item instanceof Queue.BlockedItem
                        && item.task.getName().equals(jobName)
                        && item.getCauseOfBlockage() instanceof DependencyGate.UpstreamRunning) {
                    return;
                }
            }
            Thread.sleep(50);
        }
        fail("timed out waiting for the gate to hold " + jobName);
    }
}
