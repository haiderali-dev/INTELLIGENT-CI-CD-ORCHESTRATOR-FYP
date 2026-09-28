package io.jenkins.plugins.queueoptimizer.model;

/**
 * Represents the three priority levels a developer can assign to a job.
 * Each level maps to a numeric urgency score used in the priority formula.
 */
public enum JobPriority {

    HIGH(100),
    MEDIUM(50),
    LOW(10);

    private final int urgencyScore;

    JobPriority(int urgencyScore) {
        this.urgencyScore = urgencyScore;
    }

    public int getUrgencyScore() {
        return urgencyScore;
    }
}
