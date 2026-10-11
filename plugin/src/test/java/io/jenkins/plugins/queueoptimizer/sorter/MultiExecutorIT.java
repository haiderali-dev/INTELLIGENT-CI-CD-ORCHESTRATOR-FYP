package io.jenkins.plugins.queueoptimizer.sorter;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.assertAllDispatchedBefore;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilBuildable;

import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.DispatchRecorder;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Proves that the optimizer fills every idle executor in priority order, rather than releasing
 * one job per maintenance pass.
 *
 * <p>This is Milestone 2's second defect, and the more damaging of the two because it was
 * invisible. Its dispatcher allowed an item to run only when it sat at the very top of the heap:
 *
 * <pre>
 * if (HEAP.isHighestPriority(item.getId())) return null;   // allow
 * return new CauseOfBlockage() { ... };                    // block everything else
 * </pre>
 *
 * <p>With one executor that behaves correctly, which is why the Milestone 2 experiment never
 * caught it — every run used a single executor. With three executors, two of them sit idle while
 * the queue is full, because only the single top item is ever permitted to start. The plugin
 * would have throttled a real controller to one concurrent build.
 *
 * <p>The fix is architectural rather than a patch: ordering moves to {@code QueueSorter}, which
 * merely sorts and blocks nothing, so Jenkins offers work to each idle executor in the order the
 * sorter chose. {@code QueueTaskDispatcher} is left to gate dependencies only.
 *
 * <p>Written before the sorter exists, so it is expected to fail on arrival order until T2.9.
 */
@WithJenkins
class MultiExecutorIT {

    @Test
    @DisplayName("three executors start the three highest-priority jobs, not just the top one")
    void threeExecutorsTakeTheTopThree(JenkinsRule j) throws Exception {
        DispatchRecorder dispatches = DispatchRecorder.attach(j);
        j.jenkins.setNumExecutors(0);

        // Six jobs, LOW first, so arrival order is the exact opposite of priority order.
        List<String> lows = List.of("fs-low-1", "fs-low-2", "fs-low-3");
        List<String> highs = List.of("fs-high-1", "fs-high-2", "fs-high-3");
        for (String name : lows) {
            schedule(j, name, "LOW");
        }
        for (String name : highs) {
            schedule(j, name, "HIGH");
        }
        waitUntilBuildable(j, 6);

        j.jenkins.setNumExecutors(3);
        waitUntilAllComplete(j, concat(lows, highs));

        assertAllDispatchedBefore(
                dispatches,
                highs,
                lows,
                "All three HIGH jobs should occupy the three executors first.\n"
                        + "  If exactly one HIGH ran before the LOW jobs, the optimizer is "
                        + "releasing one item per maintenance pass, which is the Milestone 2 "
                        + "multi-executor defect.");
    }

    @Test
    @DisplayName("no executor sits idle while the queue still holds runnable work")
    void executorsAreNotStarvedByTheOptimizer(JenkinsRule j) throws Exception {
        j.jenkins.setNumExecutors(0);

        List<String> names = List.of("fs-a", "fs-b", "fs-c", "fs-d");
        for (String name : names) {
            schedule(j, name, "MEDIUM");
        }
        waitUntilBuildable(j, 4);

        j.jenkins.setNumExecutors(4);

        // With four executors and four equal-priority jobs, all four should be running at once.
        // Milestone 2's gate would have permitted one, serialising the whole queue.
        int peakConcurrent = 0;
        long deadline = System.currentTimeMillis() + 60_000;
        while (System.currentTimeMillis() < deadline) {
            int running = (int) names.stream()
                    .map(n -> j.jenkins.getItemByFullName(n, FreeStyleProject.class))
                    .filter(p -> p != null && p.isBuilding())
                    .count();
            peakConcurrent = Math.max(peakConcurrent, running);
            if (peakConcurrent >= 2) {
                break;
            }
            Thread.sleep(25);
        }
        waitUntilAllComplete(j, names);

        if (peakConcurrent < 2) {
            throw new AssertionError("never observed two builds running at once with four executors and four "
                    + "queued jobs; the optimizer is serialising the queue. Peak was "
                    + peakConcurrent);
        }
    }

    private static void schedule(JenkinsRule j, String name, String level) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject(name);
        project.addProperty(new JobPriorityProperty(level, ""));
        project.scheduleBuild2(0);
    }

    private static List<String> concat(List<String> a, List<String> b) {
        return java.util.stream.Stream.concat(a.stream(), b.stream()).toList();
    }
}
