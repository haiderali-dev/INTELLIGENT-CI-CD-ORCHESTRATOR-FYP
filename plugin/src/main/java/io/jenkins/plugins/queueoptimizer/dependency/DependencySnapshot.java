package io.jenkins.plugins.queueoptimizer.dependency;

import edu.umd.cs.findbugs.annotations.NonNull;
import java.util.Collections;
import java.util.Map;
import java.util.Set;

/**
 * The dependency picture for one queue maintenance pass: which items group together, in what
 * order within a group, and what could not be resolved.
 *
 * <p>Computed fresh each pass and never persisted. A stored grouping would be able to disagree
 * with the scheduler that derives it, which is the same class of defect as the stale
 * {@code comparison.json} in Milestone 2. See {@code docs/decisions.md} D-011.
 *
 * @param groupIdByItemId the dependency group each queue item belongs to
 * @param groupSizes how many queued items each group holds
 * @param maxGroupSize the largest group present, the denominator of factor D
 * @param topologicalRankByItemId position within the group, producers first
 * @param unresolvedByItemId declared upstream names that match no known job
 * @param cyclicJobNames jobs involved in a declared dependency cycle
 */
public record DependencySnapshot(
        Map<Long, String> groupIdByItemId,
        Map<String, Integer> groupSizes,
        int maxGroupSize,
        Map<Long, Integer> topologicalRankByItemId,
        Map<Long, Set<String>> unresolvedByItemId,
        Set<String> cyclicJobNames) {

    /** An empty snapshot, for an empty queue or a disabled optimizer. */
    public static DependencySnapshot empty() {
        return new DependencySnapshot(Map.of(), Map.of(), 1, Map.of(), Map.of(), Set.of());
    }

    /** The group of an item, falling back to a unique singleton id. */
    @NonNull
    public String groupOf(long itemId) {
        return groupIdByItemId.getOrDefault(itemId, "solo-" + itemId);
    }

    /** The number of queued members in this item's group, at least 1. */
    public int groupSizeOf(long itemId) {
        return Math.max(1, groupSizes.getOrDefault(groupOf(itemId), 1));
    }

    /** This item's position within its group, producers first. */
    public int topologicalRankOf(long itemId) {
        return topologicalRankByItemId.getOrDefault(itemId, 0);
    }

    /**
     * Upstream names this item declared that match no job Jenkins knows about.
     *
     * <p>Reported, never treated as satisfied. Milestone 2 counted a missing upstream as met,
     * which let a downstream job run as though its producer had succeeded.
     */
    @NonNull
    public Set<String> unresolvedFor(long itemId) {
        return unresolvedByItemId.getOrDefault(itemId, Collections.emptySet());
    }

    /** @return true when any declared cycle was found this pass */
    public boolean hasCycle() {
        return !cyclicJobNames.isEmpty();
    }
}
