package io.jenkins.plugins.queueoptimizer.dependency;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;

/**
 * Kahn's algorithm, from report Algorithm 6.3, producing a producer-before-consumer order within
 * a dependency group and detecting declared cycles.
 *
 * <p>Union-find says which jobs belong together but treats edges as undirected, so it cannot say
 * which runs first. This restores that order in O(V + E), and reports a cycle rather than
 * throwing, because a cycle is a user configuration mistake and not an exceptional condition.
 *
 * <p>No Jenkins imports, so it is unit-testable as plain Java.
 */
public final class KahnTopologicalSort {

    private KahnTopologicalSort() {}

    /** The outcome: either an order, or the members involved in a cycle. */
    public static final class Result<T> {

        private final List<T> order;
        private final Set<T> cycleMembers;

        private Result(List<T> order, Set<T> cycleMembers) {
            this.order = order;
            this.cycleMembers = cycleMembers;
        }

        /** @return true when the graph was acyclic and {@link #getOrder()} is meaningful */
        public boolean isAcyclic() {
            return cycleMembers.isEmpty();
        }

        /**
         * The topological order, producers first.
         *
         * <p>When a cycle was found this holds the prefix that could be ordered before the
         * algorithm stalled, which is still useful for reporting.
         */
        public List<T> getOrder() {
            return List.copyOf(order);
        }

        /** @return the nodes that could never reach in-degree zero, empty when acyclic */
        public Set<T> getCycleMembers() {
            return Set.copyOf(cycleMembers);
        }
    }

    /**
     * Orders {@code nodes} so that every edge {@code from -> to} places {@code from} first.
     *
     * <p>Edges naming a node outside {@code nodes} are ignored. That is the correct reading here:
     * an upstream job that is not currently queued cannot constrain the order of the jobs that
     * are, and its absence is reported separately as an unresolved dependency rather than being
     * silently treated as satisfied, which is what Milestone 2 did.
     *
     * <p>Ties are broken by the iteration order of {@code nodes}, so the result is stable.
     *
     * @param nodes the nodes to order
     * @param edges directed edges, from producer to consumer
     * @return the order, or the cycle members when one exists
     */
    public static <T> Result<T> sort(Collection<T> nodes, Collection<Edge<T>> edges) {
        Set<T> present = new LinkedHashSet<>(nodes);

        Map<T, Set<T>> successors = new HashMap<>();
        Map<T, Integer> inDegree = new HashMap<>();
        for (T node : present) {
            successors.put(node, new LinkedHashSet<>());
            inDegree.put(node, 0);
        }

        for (Edge<T> edge : edges) {
            if (!present.contains(edge.from()) || !present.contains(edge.to())) {
                continue;
            }
            // A duplicate edge must not inflate the in-degree, or the node never reaches zero.
            if (successors.get(edge.from()).add(edge.to())) {
                inDegree.merge(edge.to(), 1, Integer::sum);
            }
        }

        Deque<T> ready = new ArrayDeque<>();
        for (T node : present) {
            if (inDegree.get(node) == 0) {
                ready.add(node);
            }
        }

        List<T> order = new ArrayList<>(present.size());
        while (!ready.isEmpty()) {
            T node = ready.poll();
            order.add(node);
            for (T next : successors.get(node)) {
                if (inDegree.merge(next, -1, Integer::sum) == 0) {
                    ready.add(next);
                }
            }
        }

        if (order.size() == present.size()) {
            return new Result<>(order, Set.of());
        }

        // Whatever never reached in-degree zero is in, or downstream of, a cycle.
        Set<T> stuck = new LinkedHashSet<>(present);
        order.forEach(stuck::remove);
        return new Result<>(order, stuck);
    }

    /** A directed dependency edge: {@code from} must complete before {@code to} starts. */
    public record Edge<T>(T from, T to) {

        public static <T> Edge<T> of(T from, T to) {
            return new Edge<>(from, to);
        }
    }

    /**
     * Convenience for the common question: is this set of declarations cyclic?
     *
     * @return the cycle members, or empty when the declarations are acyclic
     */
    public static <T> Optional<Set<T>> findCycle(Collection<T> nodes, Collection<Edge<T>> edges) {
        Result<T> result = sort(nodes, edges);
        return result.isAcyclic() ? Optional.empty() : Optional.of(result.getCycleMembers());
    }
}
