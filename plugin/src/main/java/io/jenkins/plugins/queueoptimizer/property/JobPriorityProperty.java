package io.jenkins.plugins.queueoptimizer.property;

import edu.umd.cs.findbugs.annotations.CheckForNull;
import edu.umd.cs.findbugs.annotations.NonNull;
import hudson.Extension;
import hudson.model.Job;
import hudson.model.JobProperty;
import hudson.model.JobPropertyDescriptor;
import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;
import org.jenkinsci.Symbol;
import org.kohsuke.stapler.DataBoundConstructor;

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

    /** Descriptor. Form validation and the level drop-down arrive with task T2.3. */
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
    }
}
