package io.jenkins.plugins.queueoptimizer.sorter;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The time part of the sorter's cache key: scores are computed afresh at least once per rescore
 * interval (D-072). Boundary values at the edges of an interval, and the guard against an interval
 * of zero.
 */
class RescoreBucketTest {

    @Test
    @DisplayName("at the default 60 seconds the bucket is the current minute, as Part 4.3.7 states")
    void theDefaultIsTheMinute() {
        for (long now : new long[] {0L, 59_999L, 60_000L, 119_999L, 1_792_537_085_123L}) {
            assertEquals(now / 60_000L, DynamicQueueSorter.rescoreBucket(now, 60), "at " + now + " ms");
        }
    }

    @Test
    @DisplayName("the bucket changes exactly at the edge of an interval, and not before")
    void theBucketChangesAtTheEdge() {
        assertEquals(0, DynamicQueueSorter.rescoreBucket(29_999L, 30));
        assertEquals(1, DynamicQueueSorter.rescoreBucket(30_000L, 30));
        assertEquals(0, DynamicQueueSorter.rescoreBucket(3_599_999L, 3600));
        assertEquals(1, DynamicQueueSorter.rescoreBucket(3_600_000L, 3600));
        assertEquals(0, DynamicQueueSorter.rescoreBucket(999L, 1));
        assertEquals(1, DynamicQueueSorter.rescoreBucket(1_000L, 1));
    }

    @Test
    @DisplayName("an interval of 0 or less counts as one second instead of dividing by zero")
    void aZeroIntervalCountsAsOneSecond() {
        assertEquals(5, DynamicQueueSorter.rescoreBucket(5_000L, 0));
        assertEquals(5, DynamicQueueSorter.rescoreBucket(5_000L, -1));
    }
}
