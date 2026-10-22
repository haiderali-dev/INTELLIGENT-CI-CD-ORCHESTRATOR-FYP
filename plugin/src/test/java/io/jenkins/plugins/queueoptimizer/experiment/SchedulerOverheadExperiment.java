package io.jenkins.plugins.queueoptimizer.experiment;

import static io.jenkins.plugins.queueoptimizer.QueueTestSupport.waitUntilAllComplete;
import static org.junit.jupiter.api.Assertions.fail;

import hudson.model.FreeStyleProject;
import hudson.model.Queue;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.estimation.BuildHistoryService;
import io.jenkins.plugins.queueoptimizer.heap.PriorityJobHeap;
import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.scoring.PriorityScoreCalculator;
import io.jenkins.plugins.queueoptimizer.scoring.ScoreInput;
import io.jenkins.plugins.queueoptimizer.scoring.ScoredJob;
import io.jenkins.plugins.queueoptimizer.sorter.DynamicQueueSorter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.OptionalLong;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Experiment E1: what the plugin adds to Jenkins queue maintenance.
 *
 * <p>Report section 6.6 says the scheduler adds no measurable overhead to queue maintenance at the
 * POC's scale (a queue of up to 30, a history of up to 50 builds) and leaves the evidence to the
 * testing chapter. This is that evidence. It is an experiment, not a test: it asserts nothing about
 * speed, runs only when asked for, and writes what it measured to {@code target/experiments/}:
 *
 * <pre>
 * mvn -B verify -Dit.test=SchedulerOverheadExperiment -Dtest=NONE -Dsurefire.failIfNoSpecifiedTests=false
 * </pre>
 *
 * <p>Its name matches neither Surefire's nor Failsafe's patterns, so the ordinary build never runs
 * it. Two measurements:
 *
 * <ul>
 *   <li><b>Inside Jenkins</b>: a real queue of N freestyle items, each job with build history, one
 *       in five held by the dependency gate. {@code Queue.maintain()} is timed with the optimizer
 *       off (the experiment's baseline arm, where the plugin does nothing) and on; the difference
 *       is what the plugin costs a maintenance pass. The sorter is also timed alone, from an empty
 *       cache and from a full one.
 *   <li><b>The algorithm alone</b>: scoring, sorting and heaping n items with no Jenkins at all,
 *       for n up to 3200, to see how the cost grows.
 * </ul>
 */
@WithJenkins
class SchedulerOverheadExperiment {

    private static final int[] JENKINS_QUEUE_SIZES = {10, 30, 100, 200};
    private static final int[] ALGORITHM_QUEUE_SIZES = {10, 30, 50, 100, 200, 400, 800, 1600, 3200};
    private static final int WARMUP = 5;
    private static final int REPEATS = 25;
    private static final long TIMEOUT_MILLIS = 120_000;

    @Test
    void insideJenkins(JenkinsRule j) throws Exception {
        List<String> rows = new ArrayList<>();
        rows.add("queued,held,buildable,history_records,"
                + "maintain_off_ms_median,maintain_off_ms_p90,maintain_on_ms_median,maintain_on_ms_p90,"
                + "sort_cold_ms_median,sort_cold_ms_p90,sort_cached_ms_median,sort_cached_ms_p90");
        OptimizerConfiguration config = OptimizerConfiguration.get();
        Queue queue = j.jenkins.getQueue();

        for (int n : JENKINS_QUEUE_SIZES) {
            List<FreeStyleProject> jobs = createJobs(j, n);

            // History first: every job builds once, so the estimator scores real records.
            j.jenkins.setNumExecutors(4);
            for (FreeStyleProject job : jobs) {
                job.scheduleBuild2(0);
            }
            waitUntilAllComplete(
                    j, jobs.stream().map(FreeStyleProject::getFullName).toList());

            j.jenkins.setNumExecutors(0);
            for (FreeStyleProject job : jobs) {
                job.scheduleBuild2(0);
            }
            waitUntilQueued(j, n);
            int history =
                    BuildHistoryService.recentBuilds(config.getHistoryWindow()).size();

            config.setOptimizerEnabled(false);
            double[] off = time(queue::maintain);
            config.setOptimizerEnabled(true);
            double[] on = time(queue::maintain);
            int buildable = queue.getBuildableItems().size();
            int held = (int) Arrays.stream(queue.getItems())
                    .filter(item -> item instanceof Queue.BlockedItem)
                    .count();

            // A fresh sorter has an empty cache, so this is a full pass: groups, history,
            // estimates, scores and the heap.
            double[] cold =
                    time(() -> new DynamicQueueSorter().sortBuildableItems(new ArrayList<>(queue.getBuildableItems())));
            DynamicQueueSorter warm = new DynamicQueueSorter();
            List<Queue.BuildableItem> items = new ArrayList<>(queue.getBuildableItems());
            warm.sortBuildableItems(new ArrayList<>(items));
            double[] cached = time(() -> warm.sortBuildableItems(new ArrayList<>(items)));

            rows.add(String.format(
                    Locale.ROOT,
                    "%d,%d,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f",
                    n,
                    held,
                    buildable,
                    history,
                    off[0],
                    off[1],
                    on[0],
                    on[1],
                    cold[0],
                    cold[1],
                    cached[0],
                    cached[1]));
            queue.clear();
        }
        write("scheduler-overhead-jenkins.csv", rows);
    }

    @Test
    void algorithmAlone() throws IOException {
        List<String> rows = new ArrayList<>();
        rows.add("queued,score_sort_heap_us_median,score_sort_heap_us_p90");
        for (int n : ALGORITHM_QUEUE_SIZES) {
            List<ScoreInput> queue = queueOf(n);
            for (int i = 0; i < 50; i++) {
                onePass(queue);
            }
            long[] nanos = new long[101];
            for (int i = 0; i < nanos.length; i++) {
                nanos[i] = onePass(queue);
            }
            Arrays.sort(nanos);
            rows.add(String.format(
                    Locale.ROOT,
                    "%d,%.2f,%.2f",
                    n,
                    nanos[nanos.length / 2] / 1_000.0,
                    nanos[(int) (nanos.length * 0.9)] / 1_000.0));
        }
        write("scheduler-overhead-algorithm.csv", rows);
    }

    /**
     * N jobs with the experiment workload's band mix, one in five depending on the job before it,
     * so the gate holds some items and the sorter has groups to form.
     */
    private static List<FreeStyleProject> createJobs(JenkinsRule j, int n) throws IOException {
        List<FreeStyleProject> jobs = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            FreeStyleProject job = j.createFreeStyleProject(String.format(Locale.ROOT, "e1-%d-job-%03d", n, i));
            String level = i % 10 < 3 ? "HIGH" : i % 10 < 8 ? "MEDIUM" : "LOW";
            String upstream = i % 5 == 4 ? jobs.get(i - 1).getFullName() : "";
            job.addProperty(new JobPriorityProperty(level, upstream));
            jobs.add(job);
        }
        return jobs;
    }

    private static void waitUntilQueued(JenkinsRule j, int n) throws InterruptedException {
        long deadline = System.currentTimeMillis() + TIMEOUT_MILLIS;
        while (System.currentTimeMillis() < deadline) {
            Queue queue = j.jenkins.getQueue();
            queue.maintain();
            Queue.Item[] items = queue.getItems();
            boolean settled = Arrays.stream(items).noneMatch(item -> item instanceof Queue.WaitingItem);
            if (items.length >= n && settled) {
                return;
            }
            Thread.sleep(100);
        }
        fail("timed out waiting for " + n + " queued items");
    }

    /** Median and 90th percentile, in milliseconds, after a warm-up. */
    private static double[] time(Runnable action) {
        for (int i = 0; i < WARMUP; i++) {
            action.run();
        }
        long[] nanos = new long[REPEATS];
        for (int i = 0; i < REPEATS; i++) {
            long start = System.nanoTime();
            action.run();
            nanos[i] = System.nanoTime() - start;
        }
        Arrays.sort(nanos);
        return new double[] {nanos[REPEATS / 2] / 1_000_000.0, nanos[(int) (REPEATS * 0.9)] / 1_000_000.0};
    }

    /** The same mix as SchedulerOverheadTest: three bands, groups of three, some unknown estimates. */
    private static List<ScoreInput> queueOf(int n) {
        List<ScoreInput> items = new ArrayList<>(n);
        for (int i = 0; i < n; i++) {
            PriorityLevel level =
                    switch (i % 3) {
                        case 0 -> PriorityLevel.HIGH;
                        case 1 -> PriorityLevel.MEDIUM;
                        default -> PriorityLevel.LOW;
                    };
            boolean grouped = i % 5 == 0;
            OptionalLong estimate = i % 7 == 0 ? OptionalLong.empty() : OptionalLong.of(1000L + (i * 137L) % 600_000L);
            items.add(new ScoreInput(
                    i,
                    "job-" + i,
                    level,
                    grouped ? "group-" + (i / 15) : "solo-" + i,
                    grouped ? 3 : 1,
                    grouped ? i % 3 : 0,
                    estimate,
                    (i * 37L) % 1_800_000L,
                    i));
        }
        return items;
    }

    private static long onePass(List<ScoreInput> queue) {
        long start = System.nanoTime();
        List<ScoredJob> scored = PriorityScoreCalculator.withReportDefaults().scoreAll(queue);
        scored.sort(PriorityScoreCalculator.compareForDispatch());
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.replaceAll(scored);
        long elapsed = System.nanoTime() - start;
        if (heap.size() != queue.size()) {
            fail("the heap lost items");
        }
        return elapsed;
    }

    static void write(String name, List<String> rows) throws IOException {
        Path folder = Path.of(System.getProperty("experiment.out", "target/experiments"));
        Files.createDirectories(folder);
        Files.write(folder.resolve(name), rows, StandardCharsets.UTF_8);
        List<String> about = List.of(
                "java=" + System.getProperty("java.version"),
                "os=" + System.getProperty("os.name") + " " + System.getProperty("os.version"),
                "processors=" + Runtime.getRuntime().availableProcessors(),
                "max_heap_mb=" + Runtime.getRuntime().maxMemory() / (1024 * 1024));
        Files.write(folder.resolve(name.replace(".csv", ".environment.txt")), about, StandardCharsets.UTF_8);
    }
}
