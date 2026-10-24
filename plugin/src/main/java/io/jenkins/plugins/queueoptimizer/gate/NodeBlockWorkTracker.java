package io.jenkins.plugins.queueoptimizer.gate;

import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.ExtensionList;
import hudson.model.Queue;
import hudson.model.Run;
import hudson.model.listeners.RunListener;
import hudson.model.queue.QueueListener;
import io.jenkins.plugins.queueoptimizer.resolve.JobResolver;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Which Pipeline runs have begun their work, that is, have had a node block take an executor.
 *
 * <p>{@link DependencyGate} needs to know, so that it can hold a Pipeline's first node block as it
 * holds a whole job, and still leave alone a run that is already working (D-080). The gate checks a
 * Pipeline first as its flyweight task, which leaves the queue within milliseconds. If no upstream
 * was queued or building at that moment, because the upstream was requested a moment later, the run
 * started. Its node block, exempt from the gate until D-080, then took the next free executor while
 * the upstream waited in the queue (DF-48, found by Phase 7's matrix).
 *
 * <p>The record is in memory. A run joins it when one of its node blocks leaves the queue for an
 * executor, and leaves it when the run is finalized. After a restart it is empty, so a run that
 * started before this instance was created counts as working, which is how every node block was
 * treated before D-080.
 */
@Extension
public class NodeBlockWorkTracker extends QueueListener {

    private final Set<String> working = ConcurrentHashMap.newKeySet();

    /** When this instance was created: a run that started earlier went unrecorded. */
    private final long since = System.currentTimeMillis();

    /** The instance Jenkins created. */
    @NonNull
    public static NodeBlockWorkTracker get() {
        return ExtensionList.lookupSingleton(NodeBlockWorkTracker.class);
    }

    @Override
    public void onLeft(Queue.LeftItem item) {
        if (item.isCancelled() || !JobResolver.isNodeBlock(item) || !JobResolver.consumesExecutor(item)) {
            return;
        }
        if (item.task.getOwnerExecutable() instanceof Run<?, ?> run) {
            working.add(run.getExternalizableId());
        }
    }

    /**
     * True when this node block's run has begun its work. That is the case when one of its node
     * blocks has had an executor, or when the run started before this instance existed, so its
     * earlier node blocks went unrecorded.
     *
     * <p>A node block whose run cannot be found counts as working too, which is the treatment every
     * node block had before D-080.
     */
    public boolean hasStartedWork(@NonNull Queue.Item nodeBlock) {
        if (!(nodeBlock.task.getOwnerExecutable() instanceof Run<?, ?> run)) {
            return true;
        }
        return working.contains(run.getExternalizableId()) || run.getStartTimeInMillis() < since;
    }

    void forget(@NonNull Run<?, ?> run) {
        working.remove(run.getExternalizableId());
    }

    /** Forgets each run as it is finalized, so the record holds only runs in progress. */
    @Extension
    public static class Forget extends RunListener<Run<?, ?>> {

        @Override
        public void onFinalized(Run<?, ?> run) {
            for (NodeBlockWorkTracker tracker : ExtensionList.lookup(NodeBlockWorkTracker.class)) {
                tracker.forget(run);
            }
        }
    }
}
