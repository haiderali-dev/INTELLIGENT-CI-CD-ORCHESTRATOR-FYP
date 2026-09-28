package io.jenkins.plugins.queueoptimizer.property;

import edu.umd.cs.findbugs.annotations.CheckForNull;
import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.model.Job;
import hudson.model.JobProperty;
import hudson.model.JobPropertyDescriptor;
import hudson.util.FormValidation;
import hudson.util.ListBoxModel;
import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Deque;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;
import jenkins.model.Jenkins;
import org.jenkinsci.Symbol;
import org.kohsuke.stapler.AncestorInPath;
import org.kohsuke.stapler.DataBoundConstructor;
import org.kohsuke.stapler.QueryParameter;

/**
 * Per-job configuration: the urgency level, and the upstream jobs this one depends on.
 *
 * <p>The field is named {@code level} rather than Milestone 2's {@code priority} because
 * {@link Symbol} derives the Pipeline parameter name from the data-bound constructor, and both
 * the report's Appendix D and BUILD_PROMPT 4.3.2 publish this syntax:
 *
 * <pre>
 * // Declarative
 * options { dynamicQueuePriority(level: 'HIGH', dependsOn: 'build-api') }
 * // Scripted
 * properties([dynamicQueuePriority(level: 'HIGH', dependsOn: 'build-api')])
 * </pre>
 *
 * <p>Milestone 2 job configurations still load: {@code readResolve} maps the old {@code priority}
 * element onto {@code level}. See {@code docs/decisions.md} D-005.
 *
 * <p>A property declared inside a Jenkinsfile only takes effect once that build has run, so the
 * backend also writes this property into {@code config.xml} when it creates a job.
 */
public class JobPriorityProperty extends JobProperty<Job<?, ?>> {

    @CheckForNull
    private final String level;

    @CheckForNull
    private final String dependsOn;

    /**
     * Retained only so that XStream can read a Milestone 2 {@code config.xml}, which stored the
     * urgency under {@code priority}. Never written; {@link #readResolve()} folds it into
     * {@link #level} on load.
     */
    @Deprecated
    private transient String priority;

    @DataBoundConstructor
    public JobPriorityProperty(@CheckForNull String level, @CheckForNull String dependsOn) {
        this.level = PriorityLevel.fromString(level).name();
        this.dependsOn = dependsOn == null ? "" : dependsOn.trim();
    }

    /**
     * Folds a Milestone 2 {@code <priority>} element into {@link #level} after deserialisation.
     *
     * @return this property, with the level resolved from whichever field was present
     */
    @NonNull
    protected Object readResolve() {
        if (level == null && priority != null) {
            return new JobPriorityProperty(priority, dependsOn);
        }
        return this;
    }

    /** @return the configured level name, never null */
    @NonNull
    public String getLevel() {
        return PriorityLevel.fromString(level).name();
    }

    /** @return the configured level, never null, defaulting to MEDIUM */
    @NonNull
    public PriorityLevel getPriorityLevel() {
        return PriorityLevel.fromString(level);
    }

    /**
     * The level configured on a job, defaulting to MEDIUM when the property is absent.
     *
     * <p>Lives here rather than in the sorter because the default belongs to the property: an
     * unconfigured job must be schedulable at a sensible priority, never rejected.
     */
    @NonNull
    public static PriorityLevel levelOf(@CheckForNull Job<?, ?> job) {
        if (job == null) {
            return PriorityLevel.MEDIUM;
        }
        JobPriorityProperty property = job.getProperty(JobPriorityProperty.class);
        return property == null ? PriorityLevel.MEDIUM : property.getPriorityLevel();
    }

    /** @return the raw comma-separated upstream job names, as the form stores them */
    @NonNull
    public String getDependsOn() {
        return dependsOn == null ? "" : dependsOn;
    }

    /**
     * The declared upstream job names, trimmed and with blanks removed.
     *
     * <p>No attempt is made here to check that the names exist. A missing upstream is reported
     * as unresolved rather than treated as satisfied, which is the opposite of Milestone 2's
     * behaviour and is decided by the dependency service, not by this property.
     *
     * @return the declared upstream names, possibly empty, never null
     */
    @NonNull
    public List<String> getDependsOnList() {
        if (dependsOn == null || dependsOn.isBlank()) {
            return List.of();
        }
        return Arrays.stream(dependsOn.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .collect(Collectors.toList());
    }

    @Extension
    @Symbol("dynamicQueuePriority")
    public static class DescriptorImpl extends JobPropertyDescriptor {

        @NonNull
        @Override
        public String getDisplayName() {
            return "Dynamic Queue Priority";
        }

        /**
         * Applies to every job type, including {@code WorkflowJob}.
         *
         * <p>Milestone 2's dispatcher narrowed to {@code AbstractProject} at the queue, so
         * Pipeline jobs bypassed the optimizer entirely. Nothing here may reintroduce that.
         */
        @Override
        public boolean isApplicable(Class<? extends Job> jobType) {
            return true;
        }

        /** Populates the level drop-down. */
        public ListBoxModel doFillLevelItems() {
            ListBoxModel model = new ListBoxModel();
            model.add("HIGH — runs first", PriorityLevel.HIGH.name());
            model.add("MEDIUM — default", PriorityLevel.MEDIUM.name());
            model.add("LOW — runs last", PriorityLevel.LOW.name());
            return model;
        }

        /**
         * Rejects unknown job names, self-references and declared cycles.
         *
         * <p>An unknown name is an error rather than a warning because Milestone 2 treated a
         * missing upstream as satisfied, letting a downstream job run as though its producer had
         * succeeded. Catching the typo at configuration time is the cheapest place to stop that.
         *
         * <p>A cycle is rejected here, at submission, exactly as report Algorithm 6.3 line 6
         * specifies. At runtime a cycle never blocks anything; it is reported through the API.
         */
        public FormValidation doCheckDependsOn(@QueryParameter String value, @AncestorInPath Job<?, ?> job) {
            if (value == null || value.isBlank()) {
                return FormValidation.ok();
            }

            Jenkins jenkins = Jenkins.getInstanceOrNull();
            if (jenkins == null) {
                return FormValidation.ok();
            }

            String ownName = job == null ? null : job.getFullName();
            List<String> unknown = new ArrayList<>();
            List<String> names = Arrays.stream(value.split(","))
                    .map(String::trim)
                    .filter(s -> !s.isEmpty())
                    .toList();

            for (String name : names) {
                if (ownName != null && name.equals(ownName)) {
                    return FormValidation.error("A job cannot depend on itself.");
                }
                if (jenkins.getItemByFullName(name, Job.class) == null) {
                    unknown.add(name);
                }
            }
            if (!unknown.isEmpty()) {
                return FormValidation.error(
                        "No such job: %s. A dependency that names a job Jenkins does not know is "
                                + "reported as unresolved and never treated as satisfied.",
                        String.join(", ", unknown));
            }

            if (ownName != null) {
                Optional<String> cycle = findCycleFrom(jenkins, ownName, names);
                if (cycle.isPresent()) {
                    return FormValidation.error("This creates a dependency cycle through %s.", cycle.get());
                }
            }
            return FormValidation.ok();
        }

        /**
         * Walks upstream from the proposed dependencies looking for a path back to this job.
         *
         * @return the job at which the cycle closes, or empty when the declaration is acyclic
         */
        private static Optional<String> findCycleFrom(Jenkins jenkins, String ownName, List<String> proposed) {
            Deque<String> pending = new ArrayDeque<>(proposed);
            Set<String> seen = new LinkedHashSet<>(proposed);

            while (!pending.isEmpty()) {
                String current = pending.poll();
                if (current.equals(ownName)) {
                    return Optional.of(current);
                }
                Job<?, ?> upstreamJob = jenkins.getItemByFullName(current, Job.class);
                if (upstreamJob == null) {
                    continue;
                }
                JobPriorityProperty property = upstreamJob.getProperty(JobPriorityProperty.class);
                if (property == null) {
                    continue;
                }
                for (String next : property.getDependsOnList()) {
                    if (next.equals(ownName)) {
                        return Optional.of(current);
                    }
                    if (seen.add(next)) {
                        pending.add(next);
                    }
                }
            }
            return Optional.empty();
        }
    }
}
