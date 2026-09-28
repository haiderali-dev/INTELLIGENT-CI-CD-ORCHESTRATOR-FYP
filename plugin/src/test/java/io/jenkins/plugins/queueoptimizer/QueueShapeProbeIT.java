package io.jenkins.plugins.queueoptimizer;

import hudson.model.Node;
import hudson.model.Queue;
import hudson.model.labels.LabelAtom;
import hudson.slaves.DumbSlave;
import java.util.Arrays;
import org.jenkinsci.plugins.workflow.cps.CpsFlowDefinition;
import org.jenkinsci.plugins.workflow.job.WorkflowJob;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * A diagnostic, not an assertion. Prints the actual shape of the Jenkins queue under the two
 * ways a test can hold work back, so the integration tests are built on observed behaviour
 * rather than on what the specification assumes.
 *
 * <p>BUILD_PROMPT 4.3.3 states that a Pipeline job "enters the queue as a placeholder task
 * rather than as the job". That is true of a {@code node} block, but it is not the whole
 * picture, and building {@code JobResolver} on the partial version would leave a gap. This
 * probe establishes which item shapes actually occur.
 *
 * <p>Kept in the suite deliberately: when a future Jenkins baseline changes queue behaviour,
 * this is the test whose output explains what moved.
 */
@WithJenkins
class QueueShapeProbeIT {

    @Test
    @DisplayName("probe: queue shape with zero controller executors")
    void shapeWithZeroExecutors(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);

        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "probe-zero-exec");
        job.setDefinition(new CpsFlowDefinition("node { echo 'hi' }", true));
        job.scheduleBuild2(0);

        settle(j);
        report(j, "controller numExecutors = 0");

        j.jenkins.setNumExecutors(1);
        j.waitUntilNoActivity();
    }

    @Test
    @DisplayName("probe: queue shape with an offline labelled agent")
    void shapeWithOfflineAgent(JenkinsRule j) throws Exception {
        // The controller keeps an executor so the Pipeline run itself can start; only the
        // node block has nowhere to go. This mirrors the target topology, where the
        // controller runs zero builds and labelled agents do the work.
        j.jenkins.setNumExecutors(1);

        DumbSlave agent = j.createSlave(new LabelAtom("worker"));
        agent.toComputer().disconnect(null).get();

        WorkflowJob job = j.jenkins.createProject(WorkflowJob.class, "probe-offline-agent");
        job.setDefinition(new CpsFlowDefinition("node('worker') { echo 'hi' }", true));
        job.scheduleBuild2(0);

        settle(j);
        report(j, "agent 'worker' offline, controller has 1 executor");

        agent.toComputer().connect(false).get();
        j.waitUntilNoActivity();
    }

    @Test
    @DisplayName("probe: queue shape with a busy labelled agent")
    void shapeWithBusyAgent(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(1);
        DumbSlave agent = j.createSlave(new LabelAtom("worker"));
        agent.setNumExecutors(1);

        WorkflowJob blocker = j.jenkins.createProject(WorkflowJob.class, "probe-blocker");
        blocker.setDefinition(new CpsFlowDefinition("node('worker') { sleep 8 }", true));
        blocker.scheduleBuild2(0);

        // Wait until the blocker actually owns the agent's only executor.
        long deadline = System.currentTimeMillis() + 60_000;
        while (System.currentTimeMillis() < deadline
                && agent.toComputer().countBusy() == 0) {
            Thread.sleep(100);
        }

        WorkflowJob waiting = j.jenkins.createProject(WorkflowJob.class, "probe-waiting");
        waiting.setDefinition(new CpsFlowDefinition("node('worker') { echo 'hi' }", true));
        waiting.scheduleBuild2(0);

        settle(j);
        report(j, "agent 'worker' busy with one build, one more queued");

        j.waitUntilNoActivity();
    }

    private static void settle(JenkinsRule j) throws Exception {
        // Give the run time to reach its node block, then force a maintenance pass so the
        // queue states are current.
        Thread.sleep(4000);
        j.jenkins.getQueue().maintain();
    }

    private static void report(JenkinsRule j, String scenario) {
        Queue queue = j.jenkins.getQueue();
        StringBuilder out = new StringBuilder("\n=== QUEUE SHAPE: " + scenario + " ===\n");
        out.append("items=").append(queue.getItems().length)
                .append("  buildable=").append(queue.getBuildableItems().size())
                .append("\n");
        Arrays.stream(queue.getItems()).forEach(item -> out.append(describe(item)));
        for (Node node : j.jenkins.getNodes()) {
            out.append(String.format(
                    "  node %-10s online=%-5s executors=%d busy=%d%n",
                    node.getNodeName(),
                    node.toComputer() != null && node.toComputer().isOnline(),
                    node.getNumExecutors(),
                    node.toComputer() == null ? -1 : node.toComputer().countBusy()));
        }
        out.append("  controller executors=").append(j.jenkins.getNumExecutors()).append("\n");
        System.out.println(out);
    }

    private static String describe(Queue.Item item) {
        Queue.Task task = item.task;
        StringBuilder chain = new StringBuilder();
        Queue.Task cursor = task;
        for (int hop = 0; hop < 5; hop++) {
            chain.append("\n        hop ").append(hop).append(": ")
                    .append(cursor.getClass().getName())
                    .append(cursor instanceof hudson.model.Job ? "   <-- IS A Job" : "");
            Queue.Task owner = cursor.getOwnerTask();
            if (owner == cursor) {
                chain.append("\n        (getOwnerTask() returns self; chain ends)");
                break;
            }
            cursor = owner;
        }
        return String.format(
                "  item id=%d state=%s%n    task=%s%n    isJob=%s flyweight=%s%n"
                        + "    blockage=%s%n    ownerTask chain:%s%n",
                item.getId(),
                item.getClass().getSimpleName(),
                task.getDisplayName(),
                task instanceof hudson.model.Job,
                task instanceof Queue.FlyweightTask,
                item.getCauseOfBlockage() == null
                        ? "none"
                        : item.getCauseOfBlockage().getShortDescription(),
                chain);
    }
}
