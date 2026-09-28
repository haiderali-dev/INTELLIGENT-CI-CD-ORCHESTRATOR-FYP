package io.jenkins.plugins.queueoptimizer.dependency;

import hudson.model.AbstractProject;
import hudson.model.Job;
import hudson.model.Result;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import jenkins.model.Jenkins;

import java.util.ArrayList;
import java.util.List;
import java.util.logging.Logger;

/**
 * Detects upstream job dependencies and determines whether they have
 * been satisfied before the current job is allowed to run.
 *
 * Two sources of dependency information are used:
 *   1. Jenkins native "upstream project" relationships (Build Triggers).
 *   2. The custom "Depends On" field in JobPriorityProperty (user-declared).
 */
public class DependencyResolver {

    private static final Logger LOGGER =
            Logger.getLogger(DependencyResolver.class.getName());

    /**
     * Returns the names of all upstream jobs that must complete before
     * the given job can run. Combines native Jenkins triggers with any
     * manually declared dependencies from the plugin's job property.
     */
    public List<String> getUpstreamDependencies(String jobName) {
        List<String> upstreams = new ArrayList<>();

        Job<?, ?> job = Jenkins.get().getItemByFullName(jobName, Job.class);
        if (job == null) return upstreams;

        // Native Jenkins upstream relationships
        if (job instanceof AbstractProject) {
            AbstractProject<?, ?> project = (AbstractProject<?, ?>) job;
            for (AbstractProject<?, ?> upstream : project.getUpstreamProjects()) {
                String upstreamName = upstream.getFullName();
                if (!upstreams.contains(upstreamName)) {
                    upstreams.add(upstreamName);
                    LOGGER.fine(String.format(
                            "DependencyResolver: '%s' depends on '%s' (Jenkins trigger)",
                            jobName, upstreamName));
                }
            }
        }

        // User-declared dependencies from the plugin's "Depends On" job property field
        JobPriorityProperty priorityProperty = job.getProperty(JobPriorityProperty.class);
        if (priorityProperty != null) {
            for (String declaredName : priorityProperty.getDependsOnList()) {
                if (!upstreams.contains(declaredName)) {
                    upstreams.add(declaredName);
                    LOGGER.fine(String.format(
                            "DependencyResolver: '%s' depends on '%s' (declared \"Depends On\")",
                            jobName, declaredName));
                }
            }
        }

        return upstreams;
    }

    /**
     * Returns true when every upstream dependency has a successful
     * last build — meaning the dependency chain is satisfied and
     * the current job is safe to execute.
     */
    public boolean areDependenciesMet(String jobName) {
        List<String> upstreams = getUpstreamDependencies(jobName);
        if (upstreams.isEmpty()) return true;

        for (String upstreamName : upstreams) {
            Job<?, ?> upstreamJob =
                    Jenkins.get().getItemByFullName(upstreamName, Job.class);
            if (upstreamJob == null) continue;

            var lastBuild = upstreamJob.getLastBuild();
            if (lastBuild == null || !Result.SUCCESS.equals(lastBuild.getResult())) {
                LOGGER.fine(String.format(
                        "DependencyResolver: dependency NOT met — '%s' last build is not SUCCESS",
                        upstreamName));
                return false;
            }
        }
        return true;
    }

    /**
     * Returns a 0–100 dependency score used in the priority formula.
     *
     *   Independent job (no upstreams)     → 50  (neutral)
     *   Chain job, all dependencies met    → 80  (boost: ready to continue chain)
     *   Chain job, dependencies NOT met    → 20  (penalise: can't run yet anyway)
     */
    public int calculateDependencyScore(String jobName) {
        List<String> upstreams = getUpstreamDependencies(jobName);

        if (upstreams.isEmpty()) return 50;

        if (areDependenciesMet(jobName)) {
            LOGGER.fine("DependencyResolver: '" + jobName + "' → dependency score 80 (chain ready)");
            return 80;
        }

        LOGGER.fine("DependencyResolver: '" + jobName + "' → dependency score 20 (blocked)");
        return 20;
    }
}
