package io.jenkins.plugins.queueoptimizer.heap;

import io.jenkins.plugins.queueoptimizer.scoring.PriorityScoreCalculator;
import io.jenkins.plugins.queueoptimizer.scoring.ScoredJob;
import java.util.ArrayList;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.PriorityQueue;
import java.util.concurrent.locks.ReentrantReadWriteLock;

/**
 * Thread-safe max-heap of scored jobs, report Algorithm 6.2.
 *
 * <p>Ported from Milestone 2, which got this class right. It keeps the two properties that
 * mattered there: no Jenkins imports, so it unit-tests as plain Java, and a total-order
 * comparator, so behaviour is reproducible.
 *
 * <p>That comparator is not a detail. Milestone 2 originally ordered on score alone, and because
 * repeated remove-and-reinsert cycles reshuffle which of several equally scored entries sits at
 * the root, no single item was ever consistently reported as the top across one maintenance
 * cycle, and the queue livelocked. The tie-break to enqueue time and then item id is what fixed
 * it. It is inherited here from {@link PriorityScoreCalculator#compareForDispatch()} so the heap
 * and the sorter can never disagree about order.
 *
 * <p>Backed by {@link PriorityQueue}, as report section 6.3.3 describes, with a companion map for
 * O(1) lookup by item id.
 */
public final class PriorityJobHeap {

    private final PriorityQueue<ScoredJob> heap = new PriorityQueue<>(PriorityScoreCalculator.compareForDispatch());

    private final Map<Long, ScoredJob> byItemId = new HashMap<>();

    private final ReentrantReadWriteLock lock = new ReentrantReadWriteLock();

    /** Inserts a job, or replaces the entry already held for its item id. */
    public void insertOrUpdate(ScoredJob job) {
        lock.writeLock().lock();
        try {
            ScoredJob previous = byItemId.put(job.itemId(), job);
            if (previous != null) {
                heap.remove(previous);
            }
            heap.offer(job);
        } finally {
            lock.writeLock().unlock();
        }
    }

    /**
     * Replaces the entire contents.
     *
     * <p>The sorter calls this on every pass, including a cache hit. Milestone 2's regression was
     * exactly here: a change skipped repopulation on the fast path, the heap drained as items
     * left, and the plugin silently degraded to arrival order while still reporting itself as
     * enabled. One experiment run recorded a HIGH-band wait worse than the FIFO baseline as a
     * result. See {@code docs/m2-baseline.md} section 3.2.
     */
    public void replaceAll(Collection<ScoredJob> jobs) {
        lock.writeLock().lock();
        try {
            heap.clear();
            byItemId.clear();
            for (ScoredJob job : jobs) {
                byItemId.put(job.itemId(), job);
                heap.offer(job);
            }
        } finally {
            lock.writeLock().unlock();
        }
    }

    /** @return the highest-scoring job, without removing it */
    public Optional<ScoredJob> peek() {
        lock.readLock().lock();
        try {
            return Optional.ofNullable(heap.peek());
        } finally {
            lock.readLock().unlock();
        }
    }

    /** Removes and returns the highest-scoring job. */
    public Optional<ScoredJob> extractMax() {
        lock.writeLock().lock();
        try {
            ScoredJob top = heap.poll();
            if (top != null) {
                byItemId.remove(top.itemId());
            }
            return Optional.ofNullable(top);
        } finally {
            lock.writeLock().unlock();
        }
    }

    /** Removes the entry for an item id, if present. */
    public boolean remove(long itemId) {
        lock.writeLock().lock();
        try {
            ScoredJob removed = byItemId.remove(itemId);
            return removed != null && heap.remove(removed);
        } finally {
            lock.writeLock().unlock();
        }
    }

    /** @return the entry for an item id */
    public Optional<ScoredJob> get(long itemId) {
        lock.readLock().lock();
        try {
            return Optional.ofNullable(byItemId.get(itemId));
        } finally {
            lock.readLock().unlock();
        }
    }

    /** @return true when this item id is currently the highest-scoring entry */
    public boolean isHighestPriority(long itemId) {
        lock.readLock().lock();
        try {
            ScoredJob top = heap.peek();
            return top != null && top.itemId() == itemId;
        } finally {
            lock.readLock().unlock();
        }
    }

    /**
     * Every entry in dispatch order, highest first.
     *
     * <p>A heap is only ordered at its root, so this drains a copy rather than iterating the
     * backing array, which would return an arbitrary order and make the API output look random.
     */
    public List<ScoredJob> getAllOrdered() {
        lock.readLock().lock();
        try {
            PriorityQueue<ScoredJob> copy = new PriorityQueue<>(heap);
            List<ScoredJob> ordered = new ArrayList<>(copy.size());
            while (!copy.isEmpty()) {
                ordered.add(copy.poll());
            }
            return ordered;
        } finally {
            lock.readLock().unlock();
        }
    }

    public int size() {
        lock.readLock().lock();
        try {
            return heap.size();
        } finally {
            lock.readLock().unlock();
        }
    }

    public boolean isEmpty() {
        return size() == 0;
    }

    public void clear() {
        lock.writeLock().lock();
        try {
            heap.clear();
            byItemId.clear();
        } finally {
            lock.writeLock().unlock();
        }
    }
}
