package io.jenkins.plugins.queueoptimizer.dispatcher;

import hudson.Extension;
import hudson.model.AbstractProject;
import hudson.model.queue.CauseOfBlockage;
import hudson.model.Job;
import hudson.model.Node;
import hudson.model.Queue;
import hudson.model.queue.QueueTaskDispatcher;
import io.jenkins.plugins.queueoptimizer.dependency.DependencyResolver;
import io.jenkins.plugins.queueoptimizer.estimation.BuildHistoryAnalyzer;
import io.jenkins.plugins.queueoptimizer.estimation.ExecutionTimeEstimator;
import io.jenkins.plugins.queueoptimizer.heap.PriorityJobHeap;
import io.jenkins.plugins.queueoptimizer.model.JobPriority;
import io.jenkins.plugins.queueoptimizer.model.ScoredJob;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.scoring.PriorityScoreCalculator;

import java.util.Arrays;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.logging.Logger;

/**
 * Core extension point of the Dynamic Queue Optimizer plugin.
 *
 * Jenkins calls canTake() on every registered QueueTaskDispatcher each time
 * it is about to assign a queued job to a free executor. By returning a
 * CauseOfBlockage we can prevent lower-priority jobs from running until all
 * higher-priority jobs have been dispatched first.
 *
 * Workflow inside canTake():
 *   1. Read the job's user-defined priority (HIGH / MEDIUM / LOW).
 *   2. Ask PriorityScoreCalculator for a numeric priority score.
 *   3. Insert / update the job in the shared Max-Heap.
 *   4. If this job is the top of the heap → return null (allow it to run).
 *   5. Otherwise → return a CauseOfBlockage (hold it back).
 *
 * The @Extension annotation makes Jenkins discover and register this class
 * automatically at startup — no manual wiring needed.
 */
@Extension
public class DynamicQueueDispatcher extends QueueTaskDispatcher {

    private static final Logger LOGGER =
            Logger.getLogger(DynamicQueueDispatcher.class.getName());

    /** One heap for the entire Jenkins instance (static = singleton). */
    private static final PriorityJobHeap HEAP = new PriorityJobHeap();

    private final PriorityScoreCalculator scoreCalculator;
    private final ExecutionTimeEstimator  timeEstimator;

    /**
     * Per-maintenance-cycle score cache, keyed by queue item ID.
     *
     * Jenkins calls canTake() once per buildable item per maintenance cycle.
     * The original code re-ran the O(n) rescoring pre-pass on every one of
     * those n calls, making each cycle O(n^2) calculate() calls (and, since
     * each calculate() itself scans all peers, O(n^3) estimate() calls
     * overall). The buildable-item snapshot (allQueued) is identical across
     * all canTake() calls within one cycle, so the scores computed in the
     * pre-pass are too — we only need to compute them once per cycle and
     * reuse them for the remaining calls. A cycle boundary is detected by
     * the set of buildable item IDs changing (a job started running, was
     * cancelled, or a new job was queued).
     */
    private final Object cacheLock = new Object();
    private Set<Long> cachedItemIds = Collections.emptySet();
    private Map<Long, ScoredJob> cachedScores = Collections.emptyMap();

    public DynamicQueueDispatcher() {
        BuildHistoryAnalyzer  historyAnalyzer    = new BuildHistoryAnalyzer();
        this.timeEstimator = new ExecutionTimeEstimator(historyAnalyzer);
        DependencyResolver     dependencyResolver = new DependencyResolver();
        this.scoreCalculator = new PriorityScoreCalculator(timeEstimator, dependencyResolver);
    }

    // -----------------------------------------------------------------------
    // Main extension-point method
    // -----------------------------------------------------------------------

    /**
     * Called by Jenkins to ask: "Can this item run on this node right now?"
     *
     * @return null              → allow the job to start on this node.
     * @return CauseOfBlockage  → hold the job back (Jenkins will retry later).
     */
    @Override
    public CauseOfBlockage canTake(Node node, Queue.BuildableItem item) {

        // We only manage AbstractProject-based jobs (Freestyle, Maven, etc.)
        // Pipeline jobs and other task types are left to Jenkins' default logic.
        if (!(item.task instanceof AbstractProject)) {
            return null;
        }

        Job<?, ?> job = (Job<?, ?>) item.task;

        // Read priority property; default to MEDIUM if not configured
        JobPriorityProperty prop = job.getProperty(JobPriorityProperty.class);
        JobPriority priority = (prop != null) ? prop.getPriorityEnum() : JobPriority.MEDIUM;

        // Snapshot of the current buildable queue for normalisation
        Collection<Queue.BuildableItem> allQueued =
                Arrays.asList(Queue.getInstance().getBuildableItems()
                        .toArray(new Queue.BuildableItem[0]));

        // Score and register EVERY currently-buildable item in the heap first.
        // Jenkins calls canTake() once per buildable item per maintenance cycle,
        // in queue order, to find a single item for the free executor. Without
        // this pre-pass the heap would only contain the items visited so far
        // this cycle, so the very first (FIFO-order) item would always find
        // itself alone at the top and win — making the heap a no-op.
        //
        // The pre-pass itself is only run once per maintenance cycle (cache
        // keyed by the set of buildable item IDs) instead of once per
        // canTake() call — see cachedItemIds/cachedScores above.
        Set<Long> currentItemIds = new HashSet<>();
        for (Queue.BuildableItem buildableItem : allQueued) {
            currentItemIds.add(buildableItem.getId());
        }

        Map<Long, ScoredJob> scores;
        synchronized (cacheLock) {
            if (currentItemIds.equals(cachedItemIds)) {
                scores = cachedScores;
                LOGGER.fine("Score cache hit — reusing " + scores.size() + " scores for this cycle");
            } else {
                timeEstimator.clearCache();
                scores = new HashMap<>();
                for (Queue.BuildableItem buildableItem : allQueued) {
                    if (!(buildableItem.task instanceof AbstractProject)) {
                        continue;
                    }
                    Job<?, ?> peerJob = (Job<?, ?>) buildableItem.task;
                    JobPriorityProperty peerProp = peerJob.getProperty(JobPriorityProperty.class);
                    JobPriority peerPriority = (peerProp != null) ? peerProp.getPriorityEnum() : JobPriority.MEDIUM;
                    scores.put(buildableItem.getId(),
                            scoreCalculator.calculate(buildableItem, peerPriority, allQueued));
                }
                cachedItemIds = currentItemIds;
                cachedScores = scores;
                LOGGER.fine("Score cache miss — recomputed " + scores.size() + " scores for new cycle");
            }
        }

        // Repopulate the heap from the (possibly cached) scores on every call.
        // canRun() evicts entries far more often than the buildable-item set
        // changes, so without this the heap would drain to empty between
        // cache-miss cycles. insertOrUpdate() is a cheap O(log n) heap op —
        // it's the calculate()/estimate() calls above that were expensive,
        // and those are now skipped entirely on a cache hit.
        for (ScoredJob sj : scores.values()) {
            HEAP.insertOrUpdate(sj);
        }

        ScoredJob scoredJob = scores.get(item.getId());
        if (scoredJob == null) {
            // Defensive fallback: item wasn't part of the cached pre-pass
            // (e.g. not an AbstractProject). Score it directly.
            scoredJob = scoreCalculator.calculate(item, priority, allQueued);
            HEAP.insertOrUpdate(scoredJob);
        }

        // Log the full heap state so you can trace behaviour during experiments
        LOGGER.fine("=== DynamicQueueDispatcher: heap state ===");
        for (ScoredJob sj : HEAP.getAllOrdered()) {
            LOGGER.fine(String.format("  [%6.2f] %s", sj.getPriorityScore(), sj.getJobName()));
        }

        // Decision: is this item the current highest-priority job?
        if (HEAP.isHighestPriority(item.getId())) {
            LOGGER.info("ALLOW → " + job.getFullName()
                    + " | score=" + String.format("%.2f", scoredJob.getPriorityScore()));
            return null; // Let it run
        }

        // Build a human-readable explanation of why this job is waiting
        ScoredJob top = HEAP.peek();
        String reason = String.format(
                "[DynamicQueueOptimizer] Job '%s' (score=%.2f) is waiting. " +
                "Higher-priority job '%s' (score=%.2f) must run first.",
                job.getFullName(),
                scoredJob.getPriorityScore(),
                top != null ? top.getJobName() : "unknown",
                top != null ? top.getPriorityScore() : 0.0);

        LOGGER.info("BLOCK  → " + job.getFullName() + " | " + reason);

        return new CauseOfBlockage() {
            @Override
            public String getShortDescription() {
                return reason;
            }
        };
    }

    /**
     * Called when an item is about to leave the queue (run or cancel).
     * We use this hook to remove it from our heap so stale entries
     * do not linger and distort future priority decisions.
     */
    @Override
    public CauseOfBlockage canRun(Queue.Item item) {
        HEAP.remove(item.getId());
        return null; // never block here — just clean up
    }

    /** Exposes the heap for BuildMetricsRecorder and tests. */
    public static PriorityJobHeap getHeap() {
        return HEAP;
    }
}
