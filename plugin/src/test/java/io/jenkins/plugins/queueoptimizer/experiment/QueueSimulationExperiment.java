package io.jenkins.plugins.queueoptimizer.experiment;

import io.jenkins.plugins.queueoptimizer.dependency.KahnTopologicalSort;
import io.jenkins.plugins.queueoptimizer.dependency.UnionFind;
import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import io.jenkins.plugins.queueoptimizer.scoring.PriorityScoreCalculator;
import io.jenkins.plugins.queueoptimizer.scoring.ScoreInput;
import io.jenkins.plugins.queueoptimizer.scoring.ScoredJob;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.OptionalLong;
import java.util.Random;
import java.util.Set;
import net.sf.json.JSONArray;
import net.sf.json.JSONObject;
import org.junit.jupiter.api.Test;

/**
 * Experiments E2 and E3: the scheduling algorithm on a simulated queue, with no Jenkins.
 *
 * <p>A discrete-event simulation of one queue and k executors. Scoring is the plugin's own: the
 * calculator, union-find and Kahn classes, called exactly as the sorter calls them. The gate's rule
 * is the plugin's: a job waits while one of its upstream jobs is queued or running. Nothing else
 * of Jenkins is modelled, which is the point: the algorithm's effect, without Jenkins' timing noise.
 *
 * <pre>
 * mvn -B test -Dtest=QueueSimulationExperiment -Dsurefire.failIfNoSpecifiedTests=false
 * </pre>
 *
 * <ul>
 *   <li><b>E2</b> replays Milestone 2's 30-job workload ({@code legacy/m2-poc/.../jobs.json}, all
 *       30 queued at once) under each policy, on 1 and 3 executors. A per-build overhead is
 *       calibrated from Milestone 2's measured FIFO run, and the measured plugin run's own dispatch
 *       order is replayed too, to check the timing model against what Jenkins actually did.
 *   <li><b>E3</b> asks what aging is for: independent jobs arriving at random for two hours, with
 *       Milestone 2's band mix and durations, at four utilisations and ten seeds each.
 * </ul>
 */
class QueueSimulationExperiment {

    private static final String LEGACY = "../legacy/m2-poc/experiment";
    private static final long MINUTE = 60_000L;

    enum Policy {
        /** Stock Jenkins: arrival order, and no gate, so a job may run before its upstream. */
        FIFO,
        /** Static priority: band, then arrival; with the gate. */
        URGENCY,
        /** Version 2 as built: the report's score, groups over the whole queue (D-067), aging. */
        OPTIMIZER,
        /** Version 2 before D-067: groups formed over the buildable jobs only. */
        OPTIMIZER_BUILDABLE_GROUPS,
        /** Version 2 with aging switched off, the experiment's ablation arm. */
        OPTIMIZER_NO_AGING,
        /** A given dispatch order, replayed. */
        REPLAY
    }

    record Job(int id, String name, long durationMillis, PriorityLevel level, List<String> upstream, long arrival) {}

    record Started(Job job, long start, long end) {}

    @Test
    void m2WorkloadReplay() throws IOException {
        List<Job> workload = m2Workload();
        long nominal = workload.stream().mapToLong(Job::durationMillis).sum();
        Measured baseline = measured("results/baseline-results.json", workload);
        Measured plugin = measured("results/plugin-results-run4.json", workload);
        long overhead = calibratedOverhead(workload);

        List<String> summary = new ArrayList<>();
        summary.add("source,policy,executors,estimates,makespan_s,mean_wait_s,high_mean_s,medium_mean_s,"
                + "low_mean_s,high_max_s,medium_max_s,low_max_s,violations");
        List<String> perJob = new ArrayList<>();
        perJob.add("source,policy,executors,estimates,job,level,start_s,wait_s,end_s");

        summary.add(row("measured", "M2_BASELINE_FIFO", 1, "-", baseline.starts(), workload));
        summary.add(row("measured", "M2_PLUGIN_RUN4", 1, "-", plugin.starts(), workload));
        addJobs(perJob, "measured", "M2_BASELINE_FIFO", 1, "-", baseline.starts());
        addJobs(perJob, "measured", "M2_PLUGIN_RUN4", 1, "-", plugin.starts());

        List<String> replayOrder = plugin.order();
        List<Started> replayed = simulate(workload, Policy.REPLAY, 1, overhead, true, replayOrder);
        summary.add(row("simulated", "REPLAY_M2_PLUGIN_ORDER", 1, "known", replayed, workload));
        addJobs(perJob, "simulated", "REPLAY_M2_PLUGIN_ORDER", 1, "known", replayed);

        for (int executors : new int[] {1, 3}) {
            for (boolean known : new boolean[] {true, false}) {
                for (Policy policy : List.of(
                        Policy.FIFO,
                        Policy.URGENCY,
                        Policy.OPTIMIZER,
                        Policy.OPTIMIZER_BUILDABLE_GROUPS,
                        Policy.OPTIMIZER_NO_AGING)) {
                    if (policy == Policy.FIFO && !known) {
                        continue; // FIFO never reads an estimate
                    }
                    List<Started> run = simulate(workload, policy, executors, overhead, known, List.of());
                    String estimates = known ? "known" : "unknown";
                    summary.add(row("simulated", policy.name(), executors, estimates, run, workload));
                    addJobs(perJob, "simulated", policy.name(), executors, estimates, run);
                }
            }
        }
        SchedulerOverheadExperiment.write("simulation-m2-summary.csv", summary);
        SchedulerOverheadExperiment.write("simulation-m2-jobs.csv", perJob);
        SchedulerOverheadExperiment.write(
                "simulation-m2-calibration.csv",
                List.of(
                        "nominal_total_s,measured_baseline_makespan_s,overhead_per_build_ms",
                        String.format(
                                Locale.ROOT,
                                "%.2f,%.2f,%d",
                                nominal / 1000.0,
                                baseline.makespanMillis() / 1000.0,
                                overhead)));
    }

    @Test
    void sustainedLoadAndAging() throws IOException {
        List<Job> m2 = m2Workload();
        long overhead = calibratedOverhead(m2);
        double meanService =
                m2.stream().mapToLong(Job::durationMillis).average().orElseThrow() + overhead;

        List<String> rows = new ArrayList<>();
        rows.add("utilisation,seed,policy,jobs,high_mean_s,medium_mean_s,low_mean_s,high_p95_s,medium_p95_s,"
                + "low_p95_s,high_max_s,medium_max_s,low_max_s");
        for (double utilisation : new double[] {0.7, 0.8, 0.9, 0.95}) {
            for (int seed = 1; seed <= 10; seed++) {
                List<Job> arrivals = poissonArrivals(m2, utilisation, meanService, 120 * MINUTE, seed);
                for (Policy policy :
                        List.of(Policy.FIFO, Policy.URGENCY, Policy.OPTIMIZER, Policy.OPTIMIZER_NO_AGING)) {
                    List<Started> run = simulate(arrivals, policy, 1, overhead, true, List.of());
                    rows.add(String.format(
                            Locale.ROOT,
                            "%.2f,%d,%s,%d,%s",
                            utilisation,
                            seed,
                            policy.name(),
                            run.size(),
                            bandStats(run)));
                }
            }
        }
        SchedulerOverheadExperiment.write("simulation-sustained-load.csv", rows);
    }

    // ---------------------------------------------------------------------------------------------
    // The simulator
    // ---------------------------------------------------------------------------------------------

    static List<Started> simulate(
            List<Job> jobs, Policy policy, int executors, long overhead, boolean known, List<String> order) {
        List<Job> pending = new ArrayList<>(jobs);
        pending.sort(Comparator.comparingLong(Job::arrival).thenComparingInt(Job::id));
        List<Job> waiting = new ArrayList<>();
        List<Started> running = new ArrayList<>();
        List<Started> done = new ArrayList<>();
        PriorityScoreCalculator calculator = policy == Policy.OPTIMIZER_NO_AGING
                ? new PriorityScoreCalculator(0.5, 0.3, 0.2, 0.0, 5, 0.0)
                : PriorityScoreCalculator.withReportDefaults();
        int replayed = 0;
        long now = 0;

        while (!pending.isEmpty() || !waiting.isEmpty() || !running.isEmpty()) {
            for (Started finished : List.copyOf(running)) {
                if (finished.end() <= now) {
                    running.remove(finished);
                    done.add(finished);
                }
            }
            while (!pending.isEmpty() && pending.get(0).arrival() <= now) {
                waiting.add(pending.remove(0));
            }
            int free = executors - running.size();
            if (free > 0 && !waiting.isEmpty()) {
                List<Job> picks;
                if (policy == Policy.REPLAY) {
                    picks = new ArrayList<>();
                    while (free-- > 0 && replayed < order.size()) {
                        String name = order.get(replayed);
                        Job next = waiting.stream()
                                .filter(job -> job.name().equals(name))
                                .findFirst()
                                .orElse(null);
                        if (next == null) {
                            break; // not arrived yet
                        }
                        picks.add(next);
                        replayed++;
                    }
                } else {
                    picks = choose(waiting, running, policy, calculator, known, now, free);
                }
                for (Job pick : picks) {
                    waiting.remove(pick);
                    running.add(new Started(pick, now, now + pick.durationMillis() + overhead));
                }
            }
            long next = Long.MAX_VALUE;
            for (Started job : running) {
                next = Math.min(next, job.end());
            }
            if (!pending.isEmpty()) {
                next = Math.min(next, pending.get(0).arrival());
            }
            if (next == Long.MAX_VALUE) {
                if (!waiting.isEmpty()) {
                    throw new IllegalStateException("deadlock: " + waiting);
                }
                break;
            }
            now = Math.max(now, next);
        }
        done.sort(Comparator.comparingLong(Started::start)
                .thenComparingInt(s -> s.job().id()));
        return done;
    }

    private static List<Job> choose(
            List<Job> waiting,
            List<Started> running,
            Policy policy,
            PriorityScoreCalculator calculator,
            boolean known,
            long now,
            int free) {
        Set<String> busy = new HashSet<>();
        waiting.forEach(job -> busy.add(job.name()));
        running.forEach(started -> busy.add(started.job().name()));
        List<Job> eligible = new ArrayList<>();
        for (Job job : waiting) {
            boolean held = policy != Policy.FIFO
                    && job.upstream().stream().anyMatch(up -> busy.contains(up) && !up.equals(job.name()));
            if (!held) {
                eligible.add(job);
            }
        }
        if (eligible.isEmpty()) {
            return List.of();
        }
        List<Job> ranked = new ArrayList<>(eligible);
        switch (policy) {
            case FIFO -> ranked.sort(Comparator.comparingLong(Job::arrival).thenComparingInt(Job::id));
            case URGENCY ->
                ranked.sort(Comparator.comparingDouble((Job job) -> -job.level().getUrgency())
                        .thenComparingLong(Job::arrival)
                        .thenComparingInt(Job::id));
            default -> {
                List<Job> scope = policy == Policy.OPTIMIZER_BUILDABLE_GROUPS ? eligible : waiting;
                Map<Integer, ScoredJob> scores = new HashMap<>();
                for (ScoredJob scored : calculator.scoreAll(inputs(scope, known, now))) {
                    scores.put((int) scored.itemId(), scored);
                }
                Comparator<ScoredJob> order = PriorityScoreCalculator.compareForDispatch();
                ranked.sort((a, b) -> order.compare(scores.get(a.id()), scores.get(b.id())));
            }
        }
        return ranked.subList(0, Math.min(free, ranked.size()));
    }

    /** Score inputs for the jobs in scope, grouped as DependencyGraphService groups them. */
    private static List<ScoreInput> inputs(List<Job> scope, boolean known, long now) {
        Map<String, Job> byName = new LinkedHashMap<>();
        scope.forEach(job -> byName.putIfAbsent(job.name(), job));
        UnionFind<String> groups = new UnionFind<>();
        byName.keySet().forEach(groups::add);
        List<KahnTopologicalSort.Edge<String>> edges = new ArrayList<>();
        for (Job job : scope) {
            for (String up : job.upstream()) {
                if (byName.containsKey(up) && !up.equals(job.name())) {
                    groups.union(up, job.name());
                    edges.add(KahnTopologicalSort.Edge.of(up, job.name()));
                }
            }
        }
        Map<String, String> groupOf = new HashMap<>();
        Map<String, Integer> sizeOf = new HashMap<>();
        Map<String, Integer> rankOf = new HashMap<>();
        for (Map.Entry<String, Set<String>> group : groups.groups().entrySet()) {
            Set<String> members = group.getValue();
            List<KahnTopologicalSort.Edge<String>> inside = edges.stream()
                    .filter(e -> members.contains(e.from()) && members.contains(e.to()))
                    .toList();
            List<String> sorted = KahnTopologicalSort.sort(members, inside).getOrder();
            for (int i = 0; i < sorted.size(); i++) {
                rankOf.put(sorted.get(i), i);
            }
            for (String member : members) {
                groupOf.put(member, group.getKey());
                sizeOf.put(member, members.size());
            }
        }
        List<ScoreInput> inputs = new ArrayList<>();
        for (Job job : scope) {
            inputs.add(new ScoreInput(
                    job.id(),
                    job.name(),
                    job.level(),
                    groupOf.get(job.name()),
                    sizeOf.get(job.name()),
                    rankOf.getOrDefault(job.name(), 0),
                    known ? OptionalLong.of(job.durationMillis()) : OptionalLong.empty(),
                    Math.max(0, now - job.arrival()),
                    job.arrival()));
        }
        return inputs;
    }

    // ---------------------------------------------------------------------------------------------
    // Workloads and measurements
    // ---------------------------------------------------------------------------------------------

    /** Milestone 2's 30 jobs, in file order, all queued at time zero as its trigger script did. */
    static List<Job> m2Workload() throws IOException {
        JSONArray spec = JSONArray.fromObject(read(LEGACY + "/scripts/jobs.json"));
        List<Job> jobs = new ArrayList<>();
        for (int i = 0; i < spec.size(); i++) {
            JSONObject entry = spec.getJSONObject(i);
            List<String> upstream = new ArrayList<>();
            for (Object name : entry.getJSONArray("dependsOn")) {
                upstream.add((String) name);
            }
            jobs.add(new Job(
                    i,
                    entry.getString("name"),
                    entry.getLong("duration") * 1000L,
                    PriorityLevel.fromString(entry.getString("priority")),
                    upstream,
                    0L));
        }
        return jobs;
    }

    record Measured(List<Started> starts, long makespanMillis, List<String> order) {}

    /**
     * What Jenkins adds to each build beyond its nominal sleep: the measured FIFO makespan less the
     * nominal durations, shared across the 30 builds. On one executor every order is work-conserving,
     * so FIFO's makespan is the sum of what each build really took.
     */
    static long calibratedOverhead(List<Job> workload) throws IOException {
        long nominal = workload.stream().mapToLong(Job::durationMillis).sum();
        Measured baseline = measured("results/baseline-results.json", workload);
        return Math.round((baseline.makespanMillis() - nominal) / (double) workload.size());
    }

    /** A Milestone 2 result file, in milliseconds from its t0, restricted to the 30 workload jobs. */
    private static Measured measured(String file, List<Job> workload) throws IOException {
        JSONObject result = JSONObject.fromObject(read(LEGACY + "/" + file));
        long t0 = result.getLong("t0");
        Map<String, Job> byName = new HashMap<>();
        workload.forEach(job -> byName.put(job.name(), job));
        List<Started> starts = new ArrayList<>();
        JSONArray rows = result.getJSONArray("jobs");
        for (int i = 0; i < rows.size(); i++) {
            JSONObject row = rows.getJSONObject(i);
            Job job = byName.get(row.getString("name"));
            if (job == null) {
                continue; // the baseline's leftover 31st job (docs/m2-baseline.md 4.2)
            }
            long start = row.getLong("startTime") - t0;
            starts.add(new Started(job, start, start + row.getLong("duration")));
        }
        if (starts.size() != workload.size()) {
            throw new IllegalStateException(file + " holds " + starts.size() + " of the 30 jobs");
        }
        starts.sort(Comparator.comparingLong(Started::start));
        long makespan = starts.stream().mapToLong(Started::end).max().orElseThrow();
        return new Measured(
                starts, makespan, starts.stream().map(s -> s.job().name()).toList());
    }

    /** Independent jobs arriving as a Poisson process, drawn from Milestone 2's jobs. */
    private static List<Job> poissonArrivals(
            List<Job> m2, double utilisation, double meanServiceMillis, long horizon, int seed) {
        Random random = new Random(seed);
        double rate = utilisation / meanServiceMillis;
        List<Job> jobs = new ArrayList<>();
        long now = 0;
        for (int id = 0; ; id++) {
            now += Math.round(-Math.log(1 - random.nextDouble()) / rate);
            if (now > horizon) {
                break;
            }
            Job template = m2.get(random.nextInt(m2.size()));
            jobs.add(new Job(id, "job-" + id, template.durationMillis(), template.level(), List.of(), now));
        }
        return jobs;
    }

    // ---------------------------------------------------------------------------------------------
    // Reporting
    // ---------------------------------------------------------------------------------------------

    private static String row(
            String source, String policy, int executors, String estimates, List<Started> run, List<Job> workload) {
        long firstArrival = workload.stream().mapToLong(Job::arrival).min().orElse(0);
        double makespan = (run.stream().mapToLong(Started::end).max().orElseThrow() - firstArrival) / 1000.0;
        double meanWait = run.stream()
                .mapToDouble(s -> (s.start() - s.job().arrival()) / 1000.0)
                .average()
                .orElseThrow();
        return String.format(
                Locale.ROOT,
                "%s,%s,%d,%s,%.2f,%.2f,%s,%d",
                source,
                policy,
                executors,
                estimates,
                makespan,
                meanWait,
                meansAndMaxes(run),
                violations(run));
    }

    /** The three bands' mean waits, then their longest waits. */
    private static String meansAndMaxes(List<Started> run) {
        List<String> means = new ArrayList<>();
        List<String> maxes = new ArrayList<>();
        for (PriorityLevel level : List.of(PriorityLevel.HIGH, PriorityLevel.MEDIUM, PriorityLevel.LOW)) {
            List<Double> waits = waits(run, level);
            means.add(String.format(
                    Locale.ROOT,
                    "%.2f",
                    waits.stream().mapToDouble(Double::doubleValue).average().orElse(0)));
            maxes.add(String.format(
                    Locale.ROOT,
                    "%.2f",
                    waits.stream().mapToDouble(Double::doubleValue).max().orElse(0)));
        }
        return String.join(",", means) + "," + String.join(",", maxes);
    }

    private static String bandStats(List<Started> run) {
        List<String> means = new ArrayList<>();
        List<String> p95s = new ArrayList<>();
        List<String> maxes = new ArrayList<>();
        for (PriorityLevel level : List.of(PriorityLevel.HIGH, PriorityLevel.MEDIUM, PriorityLevel.LOW)) {
            List<Double> waits = waits(run, level);
            waits.sort(Double::compare);
            means.add(String.format(
                    Locale.ROOT,
                    "%.2f",
                    waits.stream().mapToDouble(Double::doubleValue).average().orElse(0)));
            p95s.add(String.format(
                    Locale.ROOT,
                    "%.2f",
                    waits.isEmpty() ? 0 : waits.get(Math.min(waits.size() - 1, (int) (waits.size() * 0.95)))));
            maxes.add(String.format(Locale.ROOT, "%.2f", waits.isEmpty() ? 0 : waits.get(waits.size() - 1)));
        }
        return String.join(",", means) + "," + String.join(",", p95s) + "," + String.join(",", maxes);
    }

    private static List<Double> waits(List<Started> run, PriorityLevel level) {
        List<Double> waits = new ArrayList<>();
        for (Started started : run) {
            if (started.job().level() == level) {
                waits.add((started.start() - started.job().arrival()) / 1000.0);
            }
        }
        return waits;
    }

    /** Dependency edges a run broke: a job started before one of its upstream jobs had finished. */
    static int violations(List<Started> run) {
        Map<String, Started> byName = new HashMap<>();
        run.forEach(started -> byName.put(started.job().name(), started));
        int broken = 0;
        for (Started started : run) {
            for (String up : started.job().upstream()) {
                Started upstream = byName.get(up);
                if (upstream != null && started.start() < upstream.end()) {
                    broken++;
                }
            }
        }
        return broken;
    }

    private static void addJobs(
            List<String> rows, String source, String policy, int executors, String estimates, List<Started> run) {
        for (Started started : run) {
            rows.add(String.format(
                    Locale.ROOT,
                    "%s,%s,%d,%s,%s,%s,%.2f,%.2f,%.2f",
                    source,
                    policy,
                    executors,
                    estimates,
                    started.job().name(),
                    started.job().level(),
                    started.start() / 1000.0,
                    (started.start() - started.job().arrival()) / 1000.0,
                    started.end() / 1000.0));
        }
    }

    private static String read(String path) throws IOException {
        return Files.readString(Path.of(path), StandardCharsets.UTF_8);
    }
}
