package io.jenkins.plugins.queueoptimizer.heap;

import io.jenkins.plugins.queueoptimizer.model.ScoredJob;
import org.junit.Test;

import java.util.List;

import static org.junit.Assert.*;

/**
 * Unit tests for PriorityJobHeap.
 *
 * No Jenkins runtime or Mockito needed — ScoredJob has a package-private
 * constructor that accepts plain Java primitives (itemId, jobName, score).
 * This keeps tests fast, stable, and independent of Jenkins internals.
 */
public class PriorityJobHeapTest {

    // -----------------------------------------------------------------------
    // Insert / peek
    // -----------------------------------------------------------------------

    @Test
    public void topOfHeapIsAlwaysHighestScore() {
        PriorityJobHeap heap = new PriorityJobHeap();

        heap.insertOrUpdate(job(1L, "job-low",    20.0));
        heap.insertOrUpdate(job(2L, "job-high",   90.0));
        heap.insertOrUpdate(job(3L, "job-medium", 50.0));

        ScoredJob top = heap.peek();
        assertNotNull(top);
        assertEquals("job-high", top.getJobName());
        assertEquals(90.0, top.getPriorityScore(), 0.001);
    }

    @Test
    public void peekOnEmptyHeapReturnsNull() {
        assertNull(new PriorityJobHeap().peek());
    }

    @Test
    public void singleJobIsAlwaysTop() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1L, "only-job", 42.0));
        assertEquals("only-job", heap.peek().getJobName());
        assertEquals(1, heap.size());
    }

    // -----------------------------------------------------------------------
    // isHighestPriority
    // -----------------------------------------------------------------------

    @Test
    public void isHighestPriorityReturnsTrueForTopItemId() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1L, "job-high", 90.0));
        heap.insertOrUpdate(job(2L, "job-low",  20.0));

        assertTrue(heap.isHighestPriority(1L));
        assertFalse(heap.isHighestPriority(2L));
    }

    @Test
    public void isHighestPriorityOnEmptyHeapAlwaysReturnsTrue() {
        assertTrue(new PriorityJobHeap().isHighestPriority(999L));
    }

    // -----------------------------------------------------------------------
    // Remove
    // -----------------------------------------------------------------------

    @Test
    public void removingTopExposeNextHighest() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1L, "job-A", 90.0));
        heap.insertOrUpdate(job(2L, "job-B", 50.0));
        heap.insertOrUpdate(job(3L, "job-C", 70.0));

        heap.remove(1L); // remove highest (job-A score=90)

        assertEquals("job-C", heap.peek().getJobName()); // next highest = 70
        assertEquals(2, heap.size());
    }

    @Test
    public void removingNonExistentIdIsNoOp() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1L, "job-A", 80.0));
        heap.remove(999L);
        assertEquals(1, heap.size());
    }

    @Test
    public void afterRemovingAllHeapIsEmpty() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1L, "job-A", 80.0));
        heap.insertOrUpdate(job(2L, "job-B", 40.0));
        heap.remove(1L);
        heap.remove(2L);
        assertTrue(heap.isEmpty());
        assertNull(heap.peek());
    }

    // -----------------------------------------------------------------------
    // Update (insertOrUpdate replaces existing score)
    // -----------------------------------------------------------------------

    @Test
    public void updatingScoreRearrangesHeap() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1L, "job-A", 80.0));
        heap.insertOrUpdate(job(2L, "job-B", 40.0));

        // job-A is currently top; raise job-B above it
        heap.insertOrUpdate(job(2L, "job-B", 99.0));

        assertEquals("job-B", heap.peek().getJobName());
        assertEquals(99.0, heap.peek().getPriorityScore(), 0.001);
        assertEquals(2, heap.size()); // size unchanged
    }

    // -----------------------------------------------------------------------
    // getAllOrdered
    // -----------------------------------------------------------------------

    @Test
    public void getAllOrderedReturnsSortedDescending() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(1L, "low",    10.0));
        heap.insertOrUpdate(job(2L, "high",   90.0));
        heap.insertOrUpdate(job(3L, "medium", 50.0));

        List<ScoredJob> ordered = heap.getAllOrdered();
        assertEquals(3, ordered.size());
        assertEquals(90.0, ordered.get(0).getPriorityScore(), 0.001);
        assertEquals(50.0, ordered.get(1).getPriorityScore(), 0.001);
        assertEquals(10.0, ordered.get(2).getPriorityScore(), 0.001);
    }

    // -----------------------------------------------------------------------
    // contains / size / isEmpty
    // -----------------------------------------------------------------------

    @Test
    public void containsReturnsTrueOnlyForInsertedIds() {
        PriorityJobHeap heap = new PriorityJobHeap();
        heap.insertOrUpdate(job(5L, "job", 50.0));
        assertTrue(heap.contains(5L));
        assertFalse(heap.contains(6L));
    }

    // -----------------------------------------------------------------------
    // Helper — uses ScoredJob's package-private test constructor
    // -----------------------------------------------------------------------

    private ScoredJob job(long id, String name, double score) {
        return new ScoredJob(id, name, score, 60.0, false);
    }
}
