package io.jenkins.plugins.queueoptimizer.dependency;

import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.model.Job;
import hudson.model.Queue;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.resolve.JobResolver;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import jenkins.model.Jenkins;

/**
 * Builds the per-pass {@link DependencySnapshot} from the queue, applying report Algorithm 6.3:
 * union-find to group, then Kahn's algorithm to order within each group.
 *
 * <p>Edges come from two places, declared dependencies on the job property and Jenkins' own
 * upstream relationships, so a project already wired with downstream triggers groups correctly
 * without anyone restating it in the property.
 */
public final class DependencyGraphService {

    private DependencyGraphService() {}

    /**
     * Groups and orders the queued items.
     *
     * @param items the buildable items for this pass
     * @return the snapshot, never null
     */
    @NonNull
    public static DependencySnapshot build(@NonNull List<? extends Queue.Item> items) {
        if (items.isEmpty()) {
            return DependencySnapshot.empty();
        }

        // Index the queue by job name. A job can legitimately appear more than once; the first
        // occurrence owns the grouping, and the rest still resolve to the same name.
        Map<String, Long> itemIdByJobName = new LinkedHashMap<>();
        Map<Long, String> jobNameByItemId = new LinkedHashMap<>();
        for (Queue.Item item : items) {
            Optional<Job<?, ?>> job = JobResolver.resolve(item);
            if (job.isEmpty()) {
                continue;
            }
            String name = job.get().getFullName();
            jobNameByItemId.put(item.getId(), name);
            itemIdByJobName.putIfAbsent(name, item.getId());
        }
        if (jobNameByItemId.isEmpty()) {
            return DependencySnapshot.empty();
        }

        Set<String> queuedNames = new LinkedHashSet<>(itemIdByJobName.keySet());
        Map<Long, Set<String>> unresolved = new HashMap<>();
        List<KahnTopologicalSort.Edge<String>> edges = new ArrayList<>();
        UnionFind<String> unionFind = new UnionFind<>();
        queuedNames.forEach(unionFind::add);

        for (Map.Entry<Long, String> entry : jobNameByItemId.entrySet()) {
            long itemId = entry.getKey();
            String consumer = entry.getValue();

            for (String upstream : declaredUpstream(consumer)) {
                if (queuedNames.contains(upstream)) {
                    // Both ends are queued: a real ordering constraint for this pass.
                    unionFind.union(upstream, consumer);
                    edges.add(KahnTopologicalSort.Edge.of(upstream, consumer));
                } else if (!jobExists(upstream)) {
                    // Names no job at all. Reported, never treated as satisfied.
                    unresolved
                            .computeIfAbsent(itemId, key -> new LinkedHashSet<>())
                            .add(upstream);
                }
                // A known job that simply is not queued right now constrains nothing this pass.
            }
        }

        Map<String, Set<String>> groups = unionFind.groups();

        // Kahn per group, so a cycle in one group cannot disturb the ordering of another.
        Map<String, Integer> rankByJobName = new HashMap<>();
        Set<String> cyclic = new LinkedHashSet<>();
        for (Set<String> members : groups.values()) {
            List<KahnTopologicalSort.Edge<String>> groupEdges = edges.stream()
                    .filter(e -> members.contains(e.from()) && members.contains(e.to()))
                    .toList();
            KahnTopologicalSort.Result<String> sorted = KahnTopologicalSort.sort(members, groupEdges);
            List<String> order = sorted.getOrder();
            for (int i = 0; i < order.size(); i++) {
                rankByJobName.put(order.get(i), i);
            }
            if (!sorted.isAcyclic()) {
                cyclic.addAll(sorted.getCycleMembers());
                // Members stuck in a cycle still need a rank so scoring stays total. They sort
                // after everything that could be ordered, and the cycle is reported through the
                // API rather than blocking anything at runtime.
                int next = order.size();
                for (String member : sorted.getCycleMembers()) {
                    rankByJobName.put(member, next++);
                }
            }
        }

        Map<String, String> groupIdByJobName = new HashMap<>();
        Map<String, Integer> groupSizes = new HashMap<>();
        for (Map.Entry<String, Set<String>> group : groups.entrySet()) {
            String groupId = group.getKey();
            groupSizes.put(groupId, group.getValue().size());
            for (String member : group.getValue()) {
                groupIdByJobName.put(member, groupId);
            }
        }

        Map<Long, String> groupIdByItemId = new HashMap<>();
        Map<Long, Integer> rankByItemId = new HashMap<>();
        for (Map.Entry<Long, String> entry : jobNameByItemId.entrySet()) {
            String name = entry.getValue();
            groupIdByItemId.put(entry.getKey(), groupIdByJobName.getOrDefault(name, "solo-" + name));
            rankByItemId.put(entry.getKey(), rankByJobName.getOrDefault(name, 0));
        }

        int maxGroupSize =
                groupSizes.values().stream().mapToInt(Integer::intValue).max().orElse(1);

        return new DependencySnapshot(groupIdByItemId, groupSizes, maxGroupSize, rankByItemId, unresolved, cyclic);
    }

    /** Declared upstream names for a job: the property's list plus native upstream projects. */
    @NonNull
    static Set<String> declaredUpstream(String jobFullName) {
        Jenkins jenkins = Jenkins.getInstanceOrNull();
        if (jenkins == null) {
            return Set.of();
        }
        Job<?, ?> job = jenkins.getItemByFullName(jobFullName, Job.class);
        if (job == null) {
            return Set.of();
        }

        Set<String> upstream = new LinkedHashSet<>();
        JobPriorityProperty property = job.getProperty(JobPriorityProperty.class);
        if (property != null) {
            upstream.addAll(property.getDependsOnList());
        }
        if (job instanceof hudson.model.AbstractProject<?, ?> project) {
            project.getUpstreamProjects().forEach(p -> upstream.add(p.getFullName()));
        }
        return upstream;
    }

    private static boolean jobExists(String jobFullName) {
        Jenkins jenkins = Jenkins.getInstanceOrNull();
        return jenkins != null && jenkins.getItemByFullName(jobFullName, Job.class) != null;
    }
}
