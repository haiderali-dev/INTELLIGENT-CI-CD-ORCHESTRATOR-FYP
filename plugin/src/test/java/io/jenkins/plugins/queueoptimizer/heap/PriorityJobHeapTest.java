package io.jenkins.plugins.queueoptimizer.heap;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import io.jenkins.plugins.queueoptimizer.scoring.ScoredJob;
import java.util.ArrayList;
import java.util.List;
import java.util.OptionalLong;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Required by BUILD_PROMPT 4.3.10, ported from Milestone 2.
 *
 * <p>Milestone 2 got this class right, and its tie-break is the part worth preserving. Ordering on
 * score alone livelocked the queue: repeated remove-and-reinsert cycles reshuffle which of several
 * equally scored entries sits at the root, so no single item was consistently reported as the top
 * across one maintenance cycle and nothing was ever dispatched.
 *
 * <p>Plain Java, no Jenkins runtime, which is why the heap has no Jenkins imports.
 */
class PriorityJobHeapTest {

    /** A scored job with only the fields the heap's comparator reads. */
    private static ScoredJob job(long itemId, String name, double score, long inQueueSince) {
        return new ScoredJob(
                itemId,
                name,
                PriorityLevel.MEDIUM,
                0.6,
                0.0,
                0.5,
                score,
                0.0,
                score,
                score,
                OptionalLong.of(1000L),
                "solo-" + itemId,
                1,
                0,
                inQueueSince);
    }

    private static ScoredJob job(long itemId, String name, double score) {
        return job(itemId, name, score, itemId);
    }

    @Test
    @DisplayName("an empty heap reports empty and peeks to nothing")
    void emptyHeap() {
        PriorityJobHeap heap = new PriorityJobHeap();

        assertTrue(heap.isEmpty());
        assertEquals(0, heap.size());
        assertTrue(heap.peek().isEmpty());
        assertTrue(heap.extractMax().isEmpty());
        assertTrue(heap.getAllOrdered().isEmpty());
    }

    @Test
    @DisplayName("the highest score sits at the root")
    void highestScoreIsAtTheRoot() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "low", 0.30));
        heap.insertOrUpdate(job(2, "high", 0.90));
        heap.insertOrUpdate(job(3, "medium", 0.60));

        assertEquals("high", heap.peek().orElseThrow().jobName());
        assertEquals(3, heap.size());
    }

    @Test
    @DisplayName("extraction returns jobs in descending score order")
    void extractionIsOrdered() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "c", 0.30));
        heap.insertOrUpdate(job(2, "a", 0.90));
        heap.insertOrUpdate(job(3, "b", 0.60));

        List<String> order = new ArrayList<>();
        heap.extractMax().ifPresent(j -> order.add(j.jobName()));
        heap.extractMax().ifPresent(j -> order.add(j.jobName()));
        heap.extractMax().ifPresent(j -> order.add(j.jobName()));

        assertEquals(List.of("a", "b", "c"), order);
        assertTrue(heap.isEmpty(), "extraction must remove as well as return");
    }

    @Test
    @DisplayName("getAllOrdered lists every entry in dispatch order without draining")
    void getAllOrderedDoesNotDrain() {
        // A heap is only ordered at its root, so iterating the backing array would return an
        // arbitrary order and make the API's output look random.
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "c", 0.10));
        heap.insertOrUpdate(job(2, "a", 0.90));
        heap.insertOrUpdate(job(3, "b", 0.50));

        assertEquals(
                List.of("a", "b", "c"),
                heap.getAllOrdered().stream().map(ScoredJob::jobName).toList());
        assertEquals(3, heap.size(), "reading the order must not consume the heap");
    }

    @Test
    @DisplayName("inserting the same item id twice updates rather than duplicates")
    void insertOrUpdateReplaces() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "job", 0.20));
        heap.insertOrUpdate(job(1, "job", 0.95));

        assertEquals(1, heap.size(), "an item must appear once, not twice");
        assertEquals(0.95, heap.peek().orElseThrow().score(), 0.0001);
    }

    @Test
    @DisplayName("a rescored item moves to its new position")
    void rescoringReorders() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "was-low", 0.10));
        heap.insertOrUpdate(job(2, "was-high", 0.90));

        // Aging lifts the low job above the high one.
        heap.insertOrUpdate(job(1, "was-low", 0.95));

        assertEquals("was-low", heap.peek().orElseThrow().jobName());
    }

    @Test
    @DisplayName("removal by item id works and is idempotent")
    void removeByItemId() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "a", 0.50));
        heap.insertOrUpdate(job(2, "b", 0.90));

        assertTrue(heap.remove(2));
        assertEquals(1, heap.size());
        assertEquals("a", heap.peek().orElseThrow().jobName());

        assertFalse(heap.remove(2), "removing twice must not throw or corrupt the heap");
        assertFalse(heap.remove(999), "removing an unknown id is a no-op");
        assertEquals(1, heap.size());
    }

    @Test
    @DisplayName("get finds an entry by item id without changing the heap")
    void getByItemId() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(7, "seven", 0.70));

        assertEquals("seven", heap.get(7).orElseThrow().jobName());
        assertTrue(heap.get(8).isEmpty());
        assertEquals(1, heap.size());
    }

    @Test
    @DisplayName("isHighestPriority identifies the root only")
    void isHighestPriority() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "low", 0.10));
        heap.insertOrUpdate(job(2, "high", 0.90));

        assertTrue(heap.isHighestPriority(2));
        assertFalse(heap.isHighestPriority(1));
        assertFalse(heap.isHighestPriority(999), "an unknown id is not the root");
    }

    @Test
    @DisplayName("replaceAll swaps the whole contents")
    void replaceAllSwapsContents() {
        // The sorter calls this every pass, including on a cache hit. Milestone 2's regression was
        // skipping it on the fast path, after which the heap drained to empty as items left and the
        // plugin silently degraded to arrival order.
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "old-a", 0.50));
        heap.insertOrUpdate(job(2, "old-b", 0.60));

        heap.replaceAll(List.of(job(3, "new-a", 0.10), job(4, "new-b", 0.20)));

        assertEquals(2, heap.size());
        assertEquals("new-b", heap.peek().orElseThrow().jobName());
        assertTrue(heap.get(1).isEmpty(), "the old contents must be gone");
    }

    @Test
    @DisplayName("replaceAll with an empty collection clears the heap")
    void replaceAllWithEmptyClears() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "a", 0.50));

        heap.replaceAll(List.of());

        assertTrue(heap.isEmpty());
    }

    @Test
    @DisplayName("tied scores break on the earlier enqueue time, then the lower item id")
    void tiesBreakDeterministically() {
        // The livelock guard. Without a total order, repeated rebuilds swap the root among equals.
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(9, "queued-later", 0.50, 2000L));
        heap.insertOrUpdate(job(3, "queued-earlier", 0.50, 1000L));

        assertEquals("queued-earlier", heap.peek().orElseThrow().jobName());

        // Same enqueue time: the lower item id wins.
        PriorityJobHeap sameTime = new PriorityJobHeap();
        sameTime.insertOrUpdate(job(9, "higher-id", 0.50, 1000L));
        sameTime.insertOrUpdate(job(3, "lower-id", 0.50, 1000L));

        assertEquals("lower-id", sameTime.peek().orElseThrow().jobName());
    }

    @Test
    @DisplayName("the root is stable across repeated rebuilds of tied entries")
    void rootIsStableAcrossRebuilds() {
        // The exact Milestone 2 failure: many tied jobs, rebuilt repeatedly. The root must be the
        // same item every time, or no item is ever consistently dispatchable.
        List<ScoredJob> tied = new ArrayList<>();
        for (int i = 10; i >= 1; i--) {
            tied.add(job(i, "job-" + i, 0.50, 5000L));
        }

        String firstRoot = null;
        for (int rebuild = 0; rebuild < 50; rebuild++) {
            PriorityJobHeap heap = new PriorityJobHeap();
            heap.replaceAll(tied);
            String root = heap.peek().orElseThrow().jobName();
            if (firstRoot == null) {
                firstRoot = root;
            }
            assertEquals(firstRoot, root, "the root changed on rebuild " + rebuild);
        }
        assertEquals("job-1", firstRoot, "the lowest item id should win an all-equal tie");
    }

    @Test
    @DisplayName("concurrent readers and writers do not corrupt the heap")
    void concurrentAccessIsSafe() throws Exception {
        // Queue maintenance and the ranking API touch this from different threads.
        PriorityJobHeap heap = new PriorityJobHeap();
        int threads = 8;
        int perThread = 200;
        ExecutorService pool = Executors.newFixedThreadPool(threads);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch done = new CountDownLatch(threads);

        for (int t = 0; t < threads; t++) {
            final int offset = t * perThread;
            pool.submit(() -> {
                try {
                    start.await();
                    for (int i = 0; i < perThread; i++) {
                        long id = offset + i;
                        heap.insertOrUpdate(job(id, "job-" + id, (id % 100) / 100.0));
                        heap.peek();
                        heap.getAllOrdered();
                        if (i % 3 == 0) {
                            heap.remove(id);
                        }
                    }
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                } finally {
                    done.countDown();
                }
            });
        }

        start.countDown();
        assertTrue(done.await(60, TimeUnit.SECONDS), "threads did not finish; likely a deadlock");
        pool.shutdownNow();

        // The map and the heap must still agree about how many entries exist.
        assertEquals(heap.size(), heap.getAllOrdered().size(), "the backing map and heap disagree, so an entry leaked");
    }

    @Test
    @DisplayName("clear empties both the heap and its index")
    void clearEmptiesEverything() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1, "a", 0.5));

        heap.clear();

        assertTrue(heap.isEmpty());
        assertTrue(heap.get(1).isEmpty(), "the index must be cleared too, or memory leaks");
    }
}
