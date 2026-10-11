package io.jenkins.plugins.queueoptimizer.dependency;

import static io.jenkins.plugins.queueoptimizer.dependency.KahnTopologicalSort.Edge.of;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * Required by BUILD_PROMPT 4.3.10: grouping, ordering and cycle detection.
 *
 * <p>Plain Java throughout, with no Jenkins runtime, which is the reason these two classes were
 * kept free of Jenkins imports.
 */
class UnionFindKahnTest {

    @Nested
    @DisplayName("union-find grouping")
    class Grouping {

        @Test
        @DisplayName("an element with no relations is its own group")
        void singletonIsItsOwnGroup() {
            UnionFind<String> uf = new UnionFind<>();
            uf.add("solo");

            assertEquals(1, uf.groups().size());
            assertEquals(Set.of("solo"), uf.groups().values().iterator().next());
        }

        @Test
        @DisplayName("a declared chain merges into one group")
        void chainBecomesOneGroup() {
            UnionFind<String> uf = new UnionFind<>();
            uf.union("build", "test");
            uf.union("test", "deploy");

            assertTrue(uf.connected("build", "deploy"), "grouping must be transitive");
            assertEquals(1, uf.groups().size());
            assertEquals(3, uf.groups().values().iterator().next().size());
        }

        @Test
        @DisplayName("independent chains stay separate")
        void independentChainsStaySeparate() {
            UnionFind<String> uf = new UnionFind<>();
            uf.union("build-api", "test-api");
            uf.union("build-web", "test-web");

            assertFalse(uf.connected("build-api", "build-web"));
            assertEquals(2, uf.groups().size());
        }

        @Test
        @DisplayName("merging two existing groups joins every member")
        void mergingGroupsJoinsAllMembers() {
            UnionFind<String> uf = new UnionFind<>();
            uf.union("a1", "a2");
            uf.union("b1", "b2");
            uf.union("a2", "b1");

            assertEquals(1, uf.groups().size());
            assertTrue(uf.connected("a1", "b2"));
        }

        @Test
        @DisplayName("union is idempotent and order-independent")
        void unionIsIdempotent() {
            UnionFind<String> uf = new UnionFind<>();
            uf.union("a", "b");
            uf.union("b", "a");
            uf.union("a", "b");

            assertEquals(1, uf.groups().size());
            assertEquals(2, uf.size());
        }

        @Test
        @DisplayName("a long chain does not overflow the stack")
        void longChainIsIterative() {
            // Path compression is implemented iteratively on purpose: a recursive find on a
            // degenerate chain would throw inside queue maintenance, which must never happen.
            UnionFind<Integer> uf = new UnionFind<>();
            for (int i = 0; i < 100_000; i++) {
                uf.union(i, i + 1);
            }

            assertTrue(uf.connected(0, 100_000));
            assertEquals(1, uf.groups().size());
        }

        @Test
        @DisplayName("groups() reports every element exactly once")
        void groupsPartitionTheInput() {
            UnionFind<String> uf = new UnionFind<>();
            uf.union("a", "b");
            uf.add("c");
            uf.union("d", "e");

            Map<String, Set<String>> groups = uf.groups();
            int total = groups.values().stream().mapToInt(Set::size).sum();

            assertEquals(5, total, "a partition must cover every element");
            assertEquals(3, groups.size());
        }
    }

    @Nested
    @DisplayName("Kahn ordering")
    class Ordering {

        @Test
        @DisplayName("producers are ordered before consumers")
        void producersComeFirst() {
            var result = KahnTopologicalSort.sort(
                    List.of("deploy", "build", "test"), List.of(of("build", "test"), of("test", "deploy")));

            assertTrue(result.isAcyclic());
            assertEquals(List.of("build", "test", "deploy"), result.getOrder());
        }

        @Test
        @DisplayName("a fan-in waits for every producer")
        void fanInWaitsForAllProducers() {
            var result = KahnTopologicalSort.sort(
                    List.of("integration", "test-a", "test-b", "test-c"),
                    List.of(of("test-a", "integration"), of("test-b", "integration"), of("test-c", "integration")));

            assertTrue(result.isAcyclic());
            assertEquals("integration", result.getOrder().get(3), "the consumer must come after all three producers");
        }

        @Test
        @DisplayName("independent nodes keep their input order")
        void independentNodesAreStable() {
            var result = KahnTopologicalSort.sort(List.of("c", "a", "b"), List.of());

            assertTrue(result.isAcyclic());
            assertEquals(
                    List.of("c", "a", "b"),
                    result.getOrder(),
                    "a scheduling decision that varies for no reason cannot be debugged");
        }

        @Test
        @DisplayName("an edge to a node outside the group is ignored, not treated as satisfied")
        void edgesOutsideTheGroupAreIgnored() {
            // The upstream job is not queued. It cannot constrain the order of what is queued.
            // Reporting it as unresolved is DependencyGraphService's job; here it simply drops
            // out of the ordering. Milestone 2 treated a missing upstream as satisfied, which is
            // the opposite of safe.
            var result = KahnTopologicalSort.sort(
                    List.of("test", "deploy"), List.of(of("build-not-queued", "test"), of("test", "deploy")));

            assertTrue(result.isAcyclic());
            assertEquals(List.of("test", "deploy"), result.getOrder());
        }

        @Test
        @DisplayName("a duplicate edge does not deadlock the sort")
        void duplicateEdgesAreCollapsed() {
            // Counting the same edge twice would leave the consumer's in-degree permanently
            // above zero, and the whole group would look like a cycle.
            var result = KahnTopologicalSort.sort(
                    List.of("build", "test"), List.of(of("build", "test"), of("build", "test")));

            assertTrue(result.isAcyclic(), "a repeated declaration is not a cycle");
            assertEquals(List.of("build", "test"), result.getOrder());
        }

        @Test
        @DisplayName("an empty group sorts to an empty order")
        void emptyInput() {
            var result = KahnTopologicalSort.sort(List.<String>of(), List.<KahnTopologicalSort.Edge<String>>of());

            assertTrue(result.isAcyclic());
            assertTrue(result.getOrder().isEmpty());
        }
    }

    @Nested
    @DisplayName("cycle detection")
    class Cycles {

        @Test
        @DisplayName("a two-node cycle is reported, not thrown")
        void twoNodeCycle() {
            var result = KahnTopologicalSort.sort(List.of("a", "b"), List.of(of("a", "b"), of("b", "a")));

            assertFalse(result.isAcyclic());
            assertEquals(Set.of("a", "b"), result.getCycleMembers());
        }

        @Test
        @DisplayName("a longer cycle is reported with all its members")
        void threeNodeCycle() {
            var result =
                    KahnTopologicalSort.sort(List.of("a", "b", "c"), List.of(of("a", "b"), of("b", "c"), of("c", "a")));

            assertFalse(result.isAcyclic());
            assertEquals(Set.of("a", "b", "c"), result.getCycleMembers());
        }

        @Test
        @DisplayName("a self-edge is a cycle")
        void selfEdgeIsACycle() {
            var result = KahnTopologicalSort.sort(List.of("a"), List.of(of("a", "a")));

            assertFalse(result.isAcyclic());
            assertEquals(Set.of("a"), result.getCycleMembers());
        }

        @Test
        @DisplayName("acyclic nodes are still ordered when a separate cycle exists")
        void acyclicPrefixSurvivesACycleElsewhere() {
            var result = KahnTopologicalSort.sort(List.of("clean", "a", "b"), List.of(of("a", "b"), of("b", "a")));

            assertFalse(result.isAcyclic());
            assertEquals(List.of("clean"), result.getOrder());
            assertEquals(Set.of("a", "b"), result.getCycleMembers());
        }

        @Test
        @DisplayName("findCycle answers the question directly")
        void findCycleConvenience() {
            assertTrue(KahnTopologicalSort.findCycle(List.of("a", "b"), List.of(of("a", "b")))
                    .isEmpty());
            assertEquals(
                    Set.of("a", "b"),
                    KahnTopologicalSort.findCycle(List.of("a", "b"), List.of(of("a", "b"), of("b", "a")))
                            .orElseThrow());
        }
    }
}
