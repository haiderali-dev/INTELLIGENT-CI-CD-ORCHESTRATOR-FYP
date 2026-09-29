package io.jenkins.plugins.queueoptimizer.gate;

import edu.umd.cs.findbugs.annotations.CheckForNull;
import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.model.Job;
import hudson.model.Queue;
import hudson.model.Run;
import hudson.model.queue.CauseOfBlockage;
import hudson.model.queue.QueueTaskDispatcher;
import io.jenkins.plugins.queueoptimizer.config.OptimizerConfiguration;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import io.jenkins.plugins.queueoptimizer.resolve.JobResolver;
import java.util.LinkedHashSet;
import java.util.Optional;
import java.util.Set;
import java.util.logging.Level;
import java.util.logging.Logger;
import jenkins.model.Jenkins;

/**
 * Holds a job back while one of its declared upstream jobs is still queued or building.
 *
 * <p>This is the <em>only</em> thing in the plugin that ever blocks an item, and it is deliberately
 * narrow. Milestone 2 used this same extension point to do the ordering as well, permitting only
 * the single top-of-heap item to run, which throttled a multi-executor controller to one concurrent
 * build. Ordering now belongs entirely to {@code DynamicQueueSorter}, which blocks nothing.
 *
 * <p>Three rules keep the gate from doing harm:
 *
 * <ul>
 *   <li><b>Node blocks are never gated.</b> A Pipeline {@code node} block belongs to a run already
 *       in progress, whose dependencies were satisfied when the run started. Blocking it mid-build
 *       would hold an executor for a constraint that no longer applies, and could deadlock a run
 *       against itself.
 *   <li><b>An unknown upstream never blocks.</b> It is reported as unresolved instead. Milestone 2
 *       did the inverse and treated a missing upstream as satisfied, which let a downstream job run
 *       as though its producer had succeeded; this reports the problem without ever silently
 *       stalling a queue on a typo.
 *   <li><b>A failed upstream does not block.</b> Only a <em>running or queued</em> upstream does.
 *       Whether a chain should stop after a failure is a policy question the backend answers by
 *       not triggering the next job. Deciding it here would leave an item queued forever with no
 *       way for a user to tell why.
 * </ul>
 */
@Extension
public class DependencyGate extends QueueTaskDispatcher {

    private static final Logger LOGGER = Logger.getLogger(DependencyGate.class.getName());

    @CheckForNull
    @Override
    public CauseOfBlockage canRun(Queue.Item item) {
        try {
            return blockageFor(item);
        } catch (RuntimeException failure) {
            // Never let this plugin wedge the queue. Failing open means an item runs slightly
            // early; failing closed means it may never run at all.
            LOGGER.log(Level.WARNING, failure, () -> "dependency gate failed; allowing the item");
            return null;
        }
    }

    @CheckForNull
    private CauseOfBlockage blockageFor(Queue.Item item) {
        if (!OptimizerConfiguration.get().isOptimizerEnabled()) {
            // Observe-only: the experiment's baseline arm must see stock Jenkins semantics.
            return null;
        }
        if (JobResolver.isNodeBlock(item)) {
            return null;
        }
        Optional<Job<?, ?>> resolved = JobResolver.resolve(item);
        if (resolved.isEmpty()) {
            return null;
        }

        Job<?, ?> job = resolved.get();
        JobPriorityProperty property = job.getProperty(JobPriorityProperty.class);
        if (property == null) {
            return null;
        }

        for (String upstreamName : property.getDependsOnList()) {
            Job<?, ?> upstream = findJob(upstreamName);
            if (upstream == null) {
                // Unresolved, not satisfied. Reported through the API; never a blocker.
                continue;
            }
            if (upstream.getFullName().equals(job.getFullName())) {
                // A self-dependency would block the job forever. Form validation rejects it, but
                // a hand-edited config.xml can still carry one.
                continue;
            }
            if (isBuilding(upstream)) {
                return new UpstreamRunning(job.getFullName(), upstream.getFullName(), "building");
            }
            if (isQueued(upstream)) {
                return new UpstreamRunning(job.getFullName(), upstream.getFullName(), "queued");
            }
        }
        return null;
    }

    @CheckForNull
    private static Job<?, ?> findJob(String fullName) {
        Jenkins jenkins = Jenkins.getInstanceOrNull();
        return jenkins == null ? null : jenkins.getItemByFullName(fullName, Job.class);
    }

    private static boolean isBuilding(Job<?, ?> job) {
        if (job.isBuilding()) {
            return true;
        }
        Run<?, ?> last = job.getLastBuild();
        return last != null && last.isBuilding();
    }

    /**
     * True when any queue item resolves to this job.
     *
     * <p>Resolved rather than compared by task identity, so a Pipeline upstream counts whether it
     * is waiting as its own flyweight task or as a node block.
     */
    private static boolean isQueued(Job<?, ?> job) {
        Jenkins jenkins = Jenkins.getInstanceOrNull();
        if (jenkins == null) {
            return false;
        }
        String target = job.getFullName();
        for (Queue.Item queued : jenkins.getQueue().getItems()) {
            if (JobResolver.resolve(queued)
                    .map(Job::getFullName)
                    .filter(target::equals)
                    .isPresent()) {
                return true;
            }
        }
        return false;
    }

    /** Names the upstream job responsible, so the UI can show a reason a user can act on. */
    public static final class UpstreamRunning extends CauseOfBlockage {

        private final String jobName;
        private final String upstreamName;
        private final String upstreamState;

        UpstreamRunning(String jobName, String upstreamName, String upstreamState) {
            this.jobName = jobName;
            this.upstreamName = upstreamName;
            this.upstreamState = upstreamState;
        }

        @NonNull
        @Override
        public String getShortDescription() {
            return String.format("Waiting for upstream job '%s' (%s) to finish.", upstreamName, upstreamState);
        }

        /** The blocked job's full name. */
        public String getJobName() {
            return jobName;
        }

        /** The upstream job holding it. */
        public String getUpstreamName() {
            return upstreamName;
        }

        /** Either {@code building} or {@code queued}. */
        public String getUpstreamState() {
            return upstreamState;
        }
    }

    /**
     * Declared upstream names that match no job Jenkins knows about.
     *
     * <p>Exposed for the ranking API, which reports them per item so a typo is visible rather than
     * merely ineffective.
     */
    @NonNull
    public static Set<String> unresolvedUpstream(@NonNull Job<?, ?> job) {
        JobPriorityProperty property = job.getProperty(JobPriorityProperty.class);
        if (property == null) {
            return Set.of();
        }
        Set<String> unresolved = new LinkedHashSet<>();
        for (String name : property.getDependsOnList()) {
            if (findJob(name) == null) {
                unresolved.add(name);
            }
        }
        return unresolved;
    }
}
