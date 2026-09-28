package io.jenkins.plugins.queueoptimizer.heap;

import io.jenkins.plugins.queueoptimizer.model.ScoredJob;

import java.util.*;
import java.util.concurrent.locks.ReentrantReadWriteLock;
import java.util.logging.Logger;

/**
 * Thread-safe Max-Heap that orders Jenkins queue items by priority score.
 *
 * This class intentionally has NO dependency on Jenkins runtime classes
 * (Queue, Node, etc.) so it can be unit-tested with plain Java — no Jenkins
 * test harness required.
 *
 * Internally uses Java's PriorityQueue (min-heap by default).
 * A reversed comparator turns it into a max-heap: the ScoredJob with the
 * HIGHEST score sits at the front (peek/poll).
 *
 * A companion HashMap maps each item ID to its ScoredJob for O(1) lookup.
 * All public methods are guarded by a ReadWriteLock for thread safety.
 */
public class PriorityJobHeap {

    private static final Logger LOGGER =
            Logger.getLogger(PriorityJobHeap.class.getName());

    /**
     * Highest score first; ties broken by item ID (ascending) so that
     * peek()/isHighestPriority() are deterministic even when many jobs
     * share the same priority score (e.g. before any build history exists).
     * Without this tie-break, repeated remove()+offer() cycles during the
     * O(n) rescoring pre-pass can shuffle which tied job sits at the heap
     * root from call to call, so no single item is ever reported as the
     * top across a full maintenance cycle - a livelock.
     */
    private static final Comparator<ScoredJob> ORDER =
            Comparator.comparingDouble(ScoredJob::getPriorityScore).reversed()
                    .thenComparingLong(ScoredJob::getItemId);

    private final PriorityQueue<ScoredJob> heap;
    private final Map<Long, ScoredJob>     jobMap;
    private final ReentrantReadWriteLock   lock;

    public PriorityJobHeap() {
        this.heap   = new PriorityQueue<>(ORDER);
        this.jobMap = new HashMap<>();
        this.lock   = new ReentrantReadWriteLock();
    }

    // -----------------------------------------------------------------------
    // Mutating operations
    // -----------------------------------------------------------------------

    /** Inserts a new job or replaces the existing entry for the same item ID. */
    public void insertOrUpdate(ScoredJob scoredJob) {
        lock.writeLock().lock();
        try {
            long itemId = scoredJob.getItemId();

            ScoredJob existing = jobMap.get(itemId);
            if (existing != null) {
                heap.remove(existing);
            }

            heap.offer(scoredJob);
            jobMap.put(itemId, scoredJob);
            logState("insertOrUpdate");
        } finally {
            lock.writeLock().unlock();
        }
    }

    /** Removes the entry for the given item ID (job started running or was cancelled). */
    public void remove(long itemId) {
        lock.writeLock().lock();
        try {
            ScoredJob job = jobMap.remove(itemId);
            if (job != null) {
                heap.remove(job);
                LOGGER.fine("Heap: removed '" + job.getJobName()
                        + "'. Remaining=" + heap.size());
            }
        } finally {
            lock.writeLock().unlock();
        }
    }

    // -----------------------------------------------------------------------
    // Read operations
    // -----------------------------------------------------------------------

    /** Returns the highest-scoring job without removing it. Null if empty. */
    public ScoredJob peek() {
        lock.readLock().lock();
        try { return heap.peek(); }
        finally { lock.readLock().unlock(); }
    }

    /**
     * Returns true when the given item ID belongs to the current top-priority job.
     * Accepts a plain long so callers in tests never need a Queue.BuildableItem.
     */
    public boolean isHighestPriority(long itemId) {
        lock.readLock().lock();
        try {
            ScoredJob top = heap.peek();
            if (top == null) return true;    // empty heap: don't block anything
            return top.getItemId() == itemId;
        } finally {
            lock.readLock().unlock();
        }
    }

    /** Returns true when the heap already has an entry for this item ID. */
    public boolean contains(long itemId) {
        lock.readLock().lock();
        try { return jobMap.containsKey(itemId); }
        finally { lock.readLock().unlock(); }
    }

    /** Snapshot of all jobs sorted highest-score first. */
    public List<ScoredJob> getAllOrdered() {
        lock.readLock().lock();
        try {
            List<ScoredJob> sorted = new ArrayList<>(heap);
            sorted.sort(ORDER);
            return Collections.unmodifiableList(sorted);
        } finally {
            lock.readLock().unlock();
        }
    }

    public int  size()    { lock.readLock().lock(); try { return heap.size();    } finally { lock.readLock().unlock(); } }
    public boolean isEmpty() { lock.readLock().lock(); try { return heap.isEmpty(); } finally { lock.readLock().unlock(); } }

    // -----------------------------------------------------------------------
    // Helpers
    // -----------------------------------------------------------------------

    private void logState(String op) {
        ScoredJob top = heap.peek();
        LOGGER.fine(String.format("Heap[%s]: size=%d | top='%s' score=%.2f",
                op, heap.size(),
                top != null ? top.getJobName()        : "none",
                top != null ? top.getPriorityScore()  : 0.0));
    }
}
