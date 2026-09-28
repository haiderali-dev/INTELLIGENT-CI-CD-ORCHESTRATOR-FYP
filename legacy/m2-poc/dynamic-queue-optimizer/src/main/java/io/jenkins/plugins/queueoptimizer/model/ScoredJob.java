package io.jenkins.plugins.queueoptimizer.model;

import hudson.model.Queue;

/**
 * Wraps a Jenkins queue item together with its calculated priority score.
 *
 * itemId and jobName are cached as plain Java fields so that the heap and
 * scorer can be tested without any dependency on Jenkins runtime classes.
 * The original Queue.BuildableItem is kept for use by the dispatcher only.
 */
public class ScoredJob implements Comparable<ScoredJob> {

    private final Queue.BuildableItem item;  // null only in unit tests
    private final long   itemId;             // copied from item.getId()
    private final String jobName;            // copied from item.task.getFullDisplayName()
    private double priorityScore;
    private final double estimatedDurationSeconds;
    private final boolean hasDependency;

    /** Production constructor — called by the dispatcher with a real queue item. */
    public ScoredJob(Queue.BuildableItem item,
                     double priorityScore,
                     double estimatedDurationSeconds,
                     boolean hasDependency) {
        this.item                    = item;
        this.itemId                  = item.getId();
        this.jobName                 = item.task.getFullDisplayName();
        this.priorityScore           = priorityScore;
        this.estimatedDurationSeconds = estimatedDurationSeconds;
        this.hasDependency           = hasDependency;
    }

    /**
     * Test constructor — lets unit tests create ScoredJob objects without
     * needing a real (or mocked) Queue.BuildableItem.
     * The item field is left null; never call getItem() from test code.
     */
    public ScoredJob(long itemId, String jobName,
              double priorityScore,
              double estimatedDurationSeconds,
              boolean hasDependency) {
        this.item                    = null;
        this.itemId                  = itemId;
        this.jobName                 = jobName;
        this.priorityScore           = priorityScore;
        this.estimatedDurationSeconds = estimatedDurationSeconds;
        this.hasDependency           = hasDependency;
    }

    // -----------------------------------------------------------------------
    // Accessors
    // -----------------------------------------------------------------------

    /** The Jenkins queue item — only call this from dispatcher code, not tests. */
    public Queue.BuildableItem getItem()  { return item; }

    /** Stable numeric identity of this queue entry. Safe to call from anywhere. */
    public long   getItemId()            { return itemId; }

    /** Human-readable job name. Safe to call from anywhere including tests. */
    public String getJobName()           { return jobName; }

    public double getPriorityScore()     { return priorityScore; }
    public void   setPriorityScore(double s) { this.priorityScore = s; }

    public double getEstimatedDurationSeconds() { return estimatedDurationSeconds; }
    public boolean hasDependency()       { return hasDependency; }

    /**
     * Natural ordering: higher score = higher priority.
     * PriorityQueue (min-heap) uses this; the heap wrapper reverses it to get max-heap.
     */
    @Override
    public int compareTo(ScoredJob other) {
        return Double.compare(other.priorityScore, this.priorityScore);
    }

    @Override
    public String toString() {
        return String.format("ScoredJob[id=%d, name=%s, score=%.2f, estTime=%.1fs, hasDep=%b]",
                itemId, jobName, priorityScore, estimatedDurationSeconds, hasDependency);
    }
}
