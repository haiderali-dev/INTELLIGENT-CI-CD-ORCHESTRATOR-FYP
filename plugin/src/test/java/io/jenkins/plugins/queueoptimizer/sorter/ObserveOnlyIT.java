package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.metrics.MetricEvent;
import io.jenkins.plugins.queueoptimizer.metrics.MetricsPublisher;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Required by BUILD_PROMPT 4.3.10: disabled mode keeps arrival order and still records metrics.
 *
 * <p>This is the experiment's baseline arm, and it is what makes version 2's comparison honest.
 * Milestone 2 measured its baseline on a <em>separate Jenkins home with the plugin absent</em>, so
 * the two arms did not share a measurement path and any difference between them could have come
 * from the instrumentation rather than the scheduling. Here both arms run the same installation,
 * the same listeners and the same recorders; only the reordering is switched off.
 *
 * <p>Which means this test has to prove two things at once: that nothing is reordered, and that
 * everything is still measured. Either one alone would be useless.
 */
@WithJenkins
class ObserveOnlyIT {

    @Test
    @DisplayName("arrival order is preserved exactly when the optimizer is disabled")
    void arrivalOrderIsPreserved(JenkinsRule j) throws Exception {
        OptimizerConfiguration.get().setOptimizerEnabled(false);
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        // Submitted LOW first. With the optimizer on, the HIGH jobs would overtake; with it off,
        // this exact order must come back out.
        List<String> submitted = List.of("oo-low-1", "oo-low-2", "oo-high-1", "oo-high-2", "oo-medium-1");
        schedule(j, "oo-low-1", "LOW");
        schedule(j, "oo-low-2", "LOW");
        schedule(j, "oo-high-1", "HIGH");
        schedule(j, "oo-high-2", "HIGH");
        schedule(j, "oo-medium-1", "MEDIUM");
        waitUntilBuildable(j, 5);

        // One executor, so the drain order is fully determined rather than racing.
        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, submitted);

        assertEquals(
                submitted,
                dispatches.order(),
                "observe-only mode must reproduce FIFO exactly. If this drifts, the experiment's "
                        + "baseline is not a baseline and every reported improvement is suspect.");
    }

    @Test
    @DisplayName("queue and build metrics are still recorded when disabled")
    void metricsStillRecorded(JenkinsRule j) throws Exception {
        OptimizerConfiguration.get().setOptimizerEnabled(false);

        j.buildAndAssertSuccess(schedulable(j, "oo-measured", "HIGH"));

        List<MetricEvent> events = MetricsPublisher.get().getRecent(Integer.MAX_VALUE);
        List<MetricEvent.Kind> kinds = events.stream().map(MetricEvent::getKind).toList();

        assertTrue(kinds.contains(MetricEvent.Kind.QUEUE_ENTERED), "queue entry must be recorded");
        assertTrue(kinds.contains(MetricEvent.Kind.QUEUE_LEFT), "queue exit must be recorded");
        assertTrue(kinds.contains(MetricEvent.Kind.BUILD_STARTED), "build start must be recorded");
        assertTrue(kinds.contains(MetricEvent.Kind.BUILD_COMPLETED), "build completion must be recorded");

        // And every event must say which arm produced it, or the two cannot be told apart later.
        events.stream()
                .filter(e -> e.getFields().containsKey("optimizerEnabled"))
                .forEach(e -> assertEquals(
                        Boolean.FALSE,
                        e.getFields().get("optimizerEnabled"),
                        "an event recorded in observe-only mode must be labelled as such"));
    }

    @Test
    @DisplayName("a queue-left event carries the waiting time the KPIs are computed from")
    void waitTimeIsRecorded(JenkinsRule j) throws Exception {
        OptimizerConfiguration.get().setOptimizerEnabled(false);

        j.buildAndAssertSuccess(schedulable(j, "oo-waited", "MEDIUM"));

        MetricEvent left = MetricsPublisher.get().getRecent(Integer.MAX_VALUE).stream()
                .filter(e -> e.getKind() == MetricEvent.Kind.QUEUE_LEFT)
                .filter(e -> "oo-waited".equals(e.getFields().get("jobName")))
                .findFirst()
                .orElseThrow(() -> new AssertionError("no QUEUE_LEFT event for oo-waited"));

        assertTrue(left.getFields().containsKey("waitMillis"), "waitMillis is the primary KPI input");
        assertTrue(
                ((Number) left.getFields().get("waitMillis")).longValue() >= 0,
                "a negative wait would mean the clocks disagree");
        assertEquals("MEDIUM", left.getFields().get("level"), "the band must be recorded per event");
    }

    @Test
    @DisplayName("the dependency gate is inactive in observe-only mode")
    void gateIsInactiveWhenDisabled(JenkinsRule j) throws Exception {
        // Observe-only must reproduce stock Jenkins semantics, and stock Jenkins has no notion of
        // this plugin's dependsOn. Gating in the baseline arm would make the comparison unfair in
        // the plugin's favour, which is the one direction that would invalidate the result.
        OptimizerConfiguration.get().setOptimizerEnabled(false);

        // Asserted on the queue's own reason rather than on start times. The first version of
        // this test compared timestamps against a 3-second window; it passed alone and failed
        // under a full-suite run, because on a loaded machine a build can legitimately take
        // longer than the window to pick up an executor. What is actually under test is whether
        // the gate contributes a blockage, and that can be read directly.
        j.jenkins.setNumExecutors(0);

        FreeStyleProject upstream = j.createFreeStyleProject("oo-upstream");
        FreeStyleProject downstream = j.createFreeStyleProject("oo-downstream");
        downstream.addProperty(new JobPriorityProperty("HIGH", "oo-upstream"));

        upstream.scheduleBuild2(0);
        downstream.scheduleBuild2(0);
        waitUntilBuildable(j, 2);

        hudson.model.Queue.Item downstreamItem = java.util.Arrays.stream(
                        j.jenkins.getQueue().getItems())
                .filter(item -> "oo-downstream".equals(item.task.getName()))
                .findFirst()
                .orElseThrow(() -> new AssertionError("oo-downstream is not in the queue"));

        hudson.model.queue.CauseOfBlockage blockage = downstreamItem.getCauseOfBlockage();
        assertFalse(
                blockage instanceof io.jenkins.plugins.queueoptimizer.gate.DependencyGate.UpstreamRunning,
                "the gate must contribute no blockage while the optimizer is disabled, but got: "
                        + (blockage == null ? "null" : blockage.getShortDescription()));

        j.jenkins.setNumExecutors(2);
        waitUntilAllComplete(j, List.of("oo-upstream", "oo-downstream"));
    }

    @Test
    @DisplayName("the health endpoint reports the disabled state")
    void healthReportsDisabled(JenkinsRule j) throws Exception {
        OptimizerConfiguration.get().setOptimizerEnabled(false);

        String body = j.createWebClient()
                .goTo("dynamic-queue/health", "application/json")
                .getWebResponse()
                .getContentAsString();

        assertTrue(body.contains("\"enabled\":false"), "health must say which arm is running: " + body);
    }

    @Test
    @DisplayName("re-enabling restores ordering without a restart")
    void reEnablingRestoresOrdering(JenkinsRule j) throws Exception {
        // The experiment flips this between arms via JCasC, but a mid-run flip must work too,
        // otherwise a misconfigured run silently produces baseline numbers under a plugin label.
        OptimizerConfiguration.get().setOptimizerEnabled(false);
        assertFalse(OptimizerConfiguration.get().isOptimizerEnabled());

        OptimizerConfiguration.get().setOptimizerEnabled(true);
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        schedule(j, "re-low", "LOW");
        schedule(j, "re-high", "HIGH");
        waitUntilBuildable(j, 2);

        j.jenkins.setNumExecutors(1);
        waitUntilAllComplete(j, List.of("re-low", "re-high"));

        assertEquals(
                List.of("re-high", "re-low"), dispatches.order(), "ordering should resume as soon as the flag is set");
    }

    private static FreeStyleProject schedulable(JenkinsRule j, String name, String level) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject(name);
        project.addProperty(new JobPriorityProperty(level, ""));
        return project;
    }

    private static void schedule(JenkinsRule j, String name, String level) throws Exception {
        schedulable(j, name, level).scheduleBuild2(0);
    }
}
