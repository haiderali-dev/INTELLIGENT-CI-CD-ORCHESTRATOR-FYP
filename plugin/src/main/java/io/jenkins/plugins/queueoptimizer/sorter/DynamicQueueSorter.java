package io.jenkins.plugins.queueoptimizer.sorter;

import hudson.Extension;
import hudson.ExtensionList;
import hudson.model.Job;
import hudson.model.Queue;
import hudson.model.queue.QueueSorter;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.dependency.DependencyGraphService;
import io.jenkins.plugins.queueoptimizer.dependency.DependencySnapshot;
import io.jenkins.plugins.queueoptimizer.estimation.BuildHistoryService;
import io.jenkins.plugins.queueoptimizer.estimation.BuildRecord;
import io.jenkins.plugins.queueoptimizer.estimation.SimilarityEstimator;
import io.jenkins.plugins.queueoptimizer.heap.PriorityJobHeap;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.resolve.JobResolver;
import io.jenkins.plugins.queueoptimizer.scoring.PriorityScoreCalculator;
import io.jenkins.plugins.queueoptimizer.scoring.ScoreInput;
import io.jenkins.plugins.queueoptimizer.scoring.ScoredJob;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.OptionalLong;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Level;
import java.util.logging.Logger;

/**
 * Orders the buildable queue by the report's priority score.
 *
 * <p>This is the architectural correction at the centre of version 2. Milestone 2 did the same
 * job from {@code QueueTaskDispatcher#canTake}, permitting only the single top-of-heap item to
 * run and blocking everything else. On one executor that looks correct, which is why its
 * experiment never caught the problem; with three executors, two sit idle while the queue is
 * full, because only one item is ever allowed through per maintenance pass.
 *
 * <p>A {@link QueueSorter} merely orders. It blocks nothing, so Jenkins offers work to every idle
 * executor in turn and the top N items start together. Dependency gating is left to
 * {@code DependencyGate}, which is the only thing that should ever hold an item back.
 */
@Extension
public class DynamicQueueSorter extends QueueSorter {

    private static final Logger LOGGER = Logger.getLogger(DynamicQueueSorter.class.getName());

    /** One heap for the instance, exposed for the API and the tests. */
    private static final PriorityJobHeap HEAP = new PriorityJobHeap();

    private final Object cacheLock = new Object();
    private Set<Long> cachedItemIds = Collections.emptySet();
    private long cachedMinute = -1;
    private Map<Long, ScoredJob> cachedScores = Collections.emptyMap();

    private final AtomicLong sorts = new AtomicLong();
    private final AtomicLong cacheHits = new AtomicLong();
    private volatile long lastSortDurationNanos;

    /**
     * Orders the buildable items in place, highest score first.
     *
     * <p>Jenkins hands this the full buildable list on every maintenance pass and then offers the
     * items to executors in the resulting order.
     */
    @Override
    public void sortBuildableItems(List<Queue.BuildableItem> items) {
        OptimizerConfiguration config = OptimizerConfiguration.get();
        if (!config.isOptimizerEnabled()) {
            // Observe-only, the experiment's baseline arm. Arrival order is preserved exactly,
            // while the metrics recorders keep working, so both arms are measured by the same
            // code path rather than by two different Jenkins installations.
            return;
        }
        if (items == null || items.size() < 2) {
            return;
        }

        long startedAt = System.nanoTime();
        try {
            Map<Long, ScoredJob> scores = scoreWithCache(items, config);

            // Always rebuild the heap, including on a cache hit. Milestone 2's regression was
            // precisely the opposite: it skipped repopulation on the fast path, the heap drained
            // as items left the queue, and the plugin silently degraded to arrival order while
            // still reporting itself enabled. CacheEvictionRegressionIT guards this.
            HEAP.replaceAll(scores.values());

            items.sort((a, b) -> {
                ScoredJob left = scores.get(a.getId());
                ScoredJob right = scores.get(b.getId());
                if (left == null && right == null) {
                    return Long.compare(a.getId(), b.getId());
                }
                // An item that could not be scored keeps its place behind scored work rather
                // than jumping the queue on a default.
                if (left == null) {
                    return 1;
                }
                if (right == null) {
                    return -1;
                }
                return PriorityScoreCalculator.compareForDispatch().compare(left, right);
            });

            sorts.incrementAndGet();
            lastSortDurationNanos = System.nanoTime() - startedAt;
            if (LOGGER.isLoggable(Level.FINE)) {
                LOGGER.fine(
                        () -> "sorted " + items.size() + " items in " + (lastSortDurationNanos / 1_000_000.0) + " ms");
            }
        } catch (RuntimeException failure) {
            // Queue maintenance must never be broken by this plugin. An unsorted queue is a
            // degraded service; a thrown exception here is an unusable Jenkins.
            LOGGER.log(Level.WARNING, failure, () -> "priority sort failed; leaving arrival order");
        }
    }

    /**
     * Scores every item, reusing the previous pass's scores when nothing relevant has changed.
     *
     * <p>The cache key is the set of item ids plus the current minute. Including the minute is
     * what refreshes the aging bonus at least once a minute, matching the report's periodic
     * rescore, without recomputing estimates on every maintenance pass.
     */
    private Map<Long, ScoredJob> scoreWithCache(List<Queue.BuildableItem> items, OptimizerConfiguration config) {
        Set<Long> itemIds = new LinkedHashSet<>();
        for (Queue.BuildableItem item : items) {
            itemIds.add(item.getId());
        }
        long minute = System.currentTimeMillis() / 60_000L;

        synchronized (cacheLock) {
            if (minute == cachedMinute && itemIds.equals(cachedItemIds)) {
                cacheHits.incrementAndGet();
                return cachedScores;
            }
            Map<Long, ScoredJob> fresh = score(items, config);
            cachedItemIds = itemIds;
            cachedMinute = minute;
            cachedScores = fresh;
            return fresh;
        }
    }

    private Map<Long, ScoredJob> score(List<Queue.BuildableItem> items, OptimizerConfiguration config) {
        DependencySnapshot dependencies = DependencyGraphService.build(items);
        List<BuildRecord> history = BuildHistoryService.recentBuilds(config.getHistoryWindow());
        SimilarityEstimator estimator = new SimilarityEstimator(
                config.getEstimatorK(), config.getSimilarityThreshold(), config.getRecencyLambdaPerDay());

        // Estimate once per job, not once per item: two queued builds of the same job share an
        // estimate, and estimating is the expensive part of a pass.
        Map<String, OptionalLong> estimateByJob = new HashMap<>();

        long now = System.currentTimeMillis();
        List<ScoreInput> inputs = new ArrayList<>(items.size());
        for (Queue.BuildableItem item : items) {
            Optional<Job<?, ?>> resolved = JobResolver.resolve(item);
            if (resolved.isEmpty()) {
                continue;
            }
            Job<?, ?> job = resolved.get();
            String jobName = job.getFullName();

            OptionalLong estimate = estimateByJob.computeIfAbsent(
                    jobName, name -> estimator.estimate(BuildHistoryService.featuresOf(job), history));

            inputs.add(new ScoreInput(
                    item.getId(),
                    jobName,
                    JobPriorityProperty.levelOf(job),
                    dependencies.groupOf(item.getId()),
                    dependencies.groupSizeOf(item.getId()),
                    dependencies.topologicalRankOf(item.getId()),
                    estimate,
                    Math.max(0, now - item.getInQueueSince()),
                    item.getInQueueSince()));
        }

        PriorityScoreCalculator calculator = new PriorityScoreCalculator(
                config.getWeightUrgency(),
                config.getWeightDependency(),
                config.getWeightExecutionTime(),
                config.getAgingBonusPerInterval(),
                config.getAgingIntervalMinutes(),
                config.getAgingCap());

        Map<Long, ScoredJob> byItemId = new HashMap<>();
        for (ScoredJob scored : calculator.scoreAll(inputs)) {
            byItemId.put(scored.itemId(), scored);
        }
        return byItemId;
    }

    /** The shared heap, for the ranking API and the tests. */
    public static PriorityJobHeap getHeap() {
        return HEAP;
    }

    /** Nanoseconds taken by the most recent sort, for the health endpoint. */
    public long getLastSortDurationNanos() {
        return lastSortDurationNanos;
    }

    /** Fraction of passes served from the score cache, for the health endpoint. */
    public double getCacheHitRate() {
        long total = sorts.get() + cacheHits.get();
        return total == 0 ? 0.0 : (double) cacheHits.get() / total;
    }

    /** @return this instance, or null when Jenkins is not running */
    public static DynamicQueueSorter getInstance() {
        return ExtensionList.lookupSingleton(DynamicQueueSorter.class);
    }

    /**
     * Warns when another {@link QueueSorter} is installed.
     *
     * <p>Jenkins consults only the first registered sorter, so a second one from another plugin
     * silently disables this one. Better to say so at startup than to have someone debug a
     * queue that quietly stopped being ordered.
     */
    @Extension
    public static class SorterConflictWarning {

        @hudson.init.Initializer(after = hudson.init.InitMilestone.EXTENSIONS_AUGMENTED)
        public static void warnAboutCompetingSorters() {
            List<QueueSorter> sorters = ExtensionList.lookup(QueueSorter.class);
            if (sorters.size() > 1) {
                String others = sorters.stream()
                        .filter(s -> !(s instanceof DynamicQueueSorter))
                        .map(s -> s.getClass().getName())
                        .reduce((a, b) -> a + ", " + b)
                        .orElse("unknown");
                LOGGER.warning(() -> "Another QueueSorter is installed (" + others
                        + "). Jenkins uses only the first registered sorter, so queue "
                        + "optimization may be inactive.");
            }
        }
    }
}
