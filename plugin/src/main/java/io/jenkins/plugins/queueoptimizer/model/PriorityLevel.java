package io.jenkins.plugins.queueoptimizer.model;

import edu.umd.cs.findbugs.annotations.CheckForNull;
import edu.umd.cs.findbugs.annotations.NonNull;

/**
 * The three urgency levels a user can assign to a job, with the normalised value each
 * contributes to the priority score as factor {@code U}.
 *
 * <p>These values come from report Chapter 6, Algorithm 6.1, and are not tunable. Milestone 2
 * used 100 / 50 / 10 on an unnormalised scale, which is one half of why its implemented formula
 * disagreed with the published one. See {@code docs/m2-baseline.md} section 4.3.
 */
public enum PriorityLevel {
    /** Urgent work. The only level the user must justify. */
    HIGH(1.0),

    /** The default for a job that says nothing about its priority. */
    MEDIUM(0.6),

    /** Background work that may wait, protected from starvation by the aging bonus. */
    LOW(0.3);

    private final double urgency;

    PriorityLevel(double urgency) {
        this.urgency = urgency;
    }

    /**
     * The {@code U} factor for this level, in [0, 1].
     *
     * @return 1.0 for HIGH, 0.6 for MEDIUM, 0.3 for LOW
     */
    public double getUrgency() {
        return urgency;
    }

    /**
     * Parses a stored level name, falling back to {@link #MEDIUM}.
     *
     * <p>A job configuration is user-editable XML and may hold anything, including a value
     * written by an older version of this plugin. An unreadable level must never fail the
     * build or block the queue, so it degrades to the default.
     *
     * @param name a level name, possibly null, blank, or not a level at all
     * @return the matching level, or {@link #MEDIUM}
     */
    @NonNull
    public static PriorityLevel fromString(@CheckForNull String name) {
        if (name == null || name.isBlank()) {
            return MEDIUM;
        }
        try {
            return valueOf(name.trim().toUpperCase(java.util.Locale.ROOT));
        } catch (IllegalArgumentException notALevel) {
            return MEDIUM;
        }
    }
}
