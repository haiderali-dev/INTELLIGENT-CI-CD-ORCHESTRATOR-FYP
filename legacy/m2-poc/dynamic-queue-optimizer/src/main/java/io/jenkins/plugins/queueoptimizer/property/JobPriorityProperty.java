package io.jenkins.plugins.queueoptimizer.property;

import hudson.Extension;
import hudson.model.Job;
import hudson.model.JobProperty;
import hudson.model.JobPropertyDescriptor;
import hudson.util.ListBoxModel;
import io.jenkins.plugins.queueoptimizer.model.JobPriority;
import org.kohsuke.stapler.DataBoundConstructor;

import java.util.Arrays;
import java.util.List;
import java.util.stream.Collectors;

/**
 * Adds a "Dynamic Queue Priority" section to the Jenkins job configuration page.
 *
 * When a developer opens a job's Configure page, they will see:
 *   - A dropdown to select HIGH / MEDIUM / LOW priority.
 *   - A text field to declare upstream dependencies (comma-separated job names).
 *
 * The values entered here are read by DynamicQueueDispatcher at queue time.
 */
public class JobPriorityProperty extends JobProperty<Job<?, ?>> {

    private final String priority;   // Stored as String to survive serialisation
    private final String dependsOn;  // Comma-separated upstream job names

    @DataBoundConstructor
    public JobPriorityProperty(String priority, String dependsOn) {
        this.priority  = (priority  != null && !priority.isBlank())  ? priority.trim()  : JobPriority.MEDIUM.name();
        this.dependsOn = (dependsOn != null && !dependsOn.isBlank()) ? dependsOn.trim() : "";
    }

    /**
     * Returns the priority as a String matching the option values in doFillPriorityItems().
     *
     * Jenkins' <f:select field="priority"> calls getPriority() to find the
     * currently selected option — the returned value must equal one of the
     * option values ("HIGH", "MEDIUM", or "LOW").
     */
    public String getPriority() {
        return priority != null ? priority : JobPriority.MEDIUM.name();
    }

    /**
     * Returns the priority as a JobPriority enum.
     * Called by DynamicQueueDispatcher and scoring components.
     */
    public JobPriority getPriorityEnum() {
        try {
            return JobPriority.valueOf(priority);
        } catch (IllegalArgumentException e) {
            return JobPriority.MEDIUM;
        }
    }

    /** Raw comma-separated string — used by the Jelly config form. */
    public String getDependsOn() {
        return dependsOn;
    }

    /** Parsed list of upstream job names, trimmed. */
    public List<String> getDependsOnList() {
        if (dependsOn == null || dependsOn.isBlank()) return List.of();
        return Arrays.stream(dependsOn.split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .collect(Collectors.toList());
    }

    // -----------------------------------------------------------------------
    // Descriptor — registers this property with Jenkins and renders the UI
    // -----------------------------------------------------------------------

    @Extension
    public static class DescriptorImpl extends JobPropertyDescriptor {

        @Override
        public String getDisplayName() {
            return "Dynamic Queue Priority";
        }

        /** Makes this property available on every job type. */
        @Override
        public boolean isApplicable(Class<? extends Job> jobType) {
            return true;
        }

        /**
         * Populates the priority dropdown.
         *
         * Jenkins' <f:select field="priority"> automatically calls
         * doFillPriorityItems() on the descriptor to get the list of options.
         * Each ListBoxModel.Option has a display name and a value (the enum name).
         */
        public ListBoxModel doFillPriorityItems() {
            ListBoxModel model = new ListBoxModel();
            model.add("HIGH   — runs first",   JobPriority.HIGH.name());
            model.add("MEDIUM — default",       JobPriority.MEDIUM.name());
            model.add("LOW    — runs last",     JobPriority.LOW.name());
            return model;
        }
    }
}
