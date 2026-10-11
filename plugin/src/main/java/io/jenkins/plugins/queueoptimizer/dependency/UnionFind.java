package io.jenkins.plugins.queueoptimizer.dependency;

import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * Disjoint-set forest with union by rank and path compression, from report Algorithm 6.3.
 *
 * <p>Deliberately free of any Jenkins import so it can be unit-tested as plain Java, and generic
 * over the element type so the tests can use strings rather than constructing queue items.
 *
 * <p>Both optimisations are needed for the amortised inverse-Ackermann bound the report claims;
 * either one alone gives a worse guarantee. At the sizes this plugin sees the difference is
 * academic, but the report analyses this structure specifically, so it implements that structure.
 *
 * @param <T> the element type, which must have sensible equals and hashCode
 */
public final class UnionFind<T> {

    private final Map<T, T> parent = new HashMap<>();
    private final Map<T, Integer> rank = new HashMap<>();

    /** Adds an element as its own singleton set. Does nothing if already present. */
    public void add(T element) {
        parent.putIfAbsent(element, element);
        rank.putIfAbsent(element, 0);
    }

    /**
     * The representative of the set containing {@code element}, adding it first if unknown.
     *
     * <p>Iterative rather than recursive: a deep chain in a pathological graph would otherwise
     * risk a stack overflow inside queue maintenance, which is not a place to throw.
     */
    public T find(T element) {
        add(element);
        T root = element;
        while (!root.equals(parent.get(root))) {
            root = parent.get(root);
        }
        // Path compression: point everything on the walk straight at the root.
        T cursor = element;
        while (!cursor.equals(root)) {
            T next = parent.get(cursor);
            parent.put(cursor, root);
            cursor = next;
        }
        return root;
    }

    /** Merges the sets containing {@code a} and {@code b}, by rank. */
    public void union(T a, T b) {
        T rootA = find(a);
        T rootB = find(b);
        if (rootA.equals(rootB)) {
            return;
        }
        int rankA = rank.getOrDefault(rootA, 0);
        int rankB = rank.getOrDefault(rootB, 0);
        if (rankA < rankB) {
            parent.put(rootA, rootB);
        } else if (rankA > rankB) {
            parent.put(rootB, rootA);
        } else {
            parent.put(rootB, rootA);
            rank.put(rootA, rankA + 1);
        }
    }

    /** @return true when both elements are in the same set */
    public boolean connected(T a, T b) {
        return find(a).equals(find(b));
    }

    /**
     * The partition, keyed by representative.
     *
     * <p>Insertion-ordered so that grouping is reproducible run to run, which matters because a
     * scheduling decision that varies for no reason is one nobody can debug.
     */
    public Map<T, Set<T>> groups() {
        Map<T, Set<T>> result = new LinkedHashMap<>();
        for (T element : parent.keySet()) {
            result.computeIfAbsent(find(element), key -> new LinkedHashSet<>()).add(element);
        }
        return result;
    }

    /** @return the number of elements tracked */
    public int size() {
        return parent.size();
    }
}
