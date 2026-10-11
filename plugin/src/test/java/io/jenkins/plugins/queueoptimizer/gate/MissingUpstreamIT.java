package io.jenkins.plugins.queueoptimizer.gate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.model.FreeStyleProject;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * Required by BUILD_PROMPT 4.3.10: an unknown upstream never blocks, and is reported as unresolved.
 *
 * <p>This is Milestone 2 known problem 5, inverted. There, a missing upstream job counted as
 * <em>satisfied</em>, so a downstream job ran as though its producer had succeeded — the least safe
 * possible reading of a typo.
 *
 * <p>The opposite extreme is no better. Treating an unknown name as unsatisfied would let one
 * mistyped job name stall a queue indefinitely, with a cause of blockage naming a job nobody can
 * find. So the name is reported as unresolved through the API and form validation rejects it at
 * configuration time, while the queue itself keeps moving.
 */
@WithJenkins
class MissingUpstreamIT {

    @Test
    @DisplayName("a job depending on a nonexistent upstream still runs")
    void unknownUpstreamDoesNotBlock(JenkinsRule j) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject("depends-on-ghost");
        project.addProperty(new JobPriorityProperty("MEDIUM", "no-such-job"));

        // The assertion is that this returns at all rather than timing out.
        j.buildAndAssertSuccess(project);
    }

    @Test
    @DisplayName("the unknown name is reported as unresolved")
    void unknownUpstreamIsReported(JenkinsRule j) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject("reports-ghost");
        project.addProperty(new JobPriorityProperty("MEDIUM", "no-such-job, also-missing"));

        Set<String> unresolved = DependencyGate.unresolvedUpstream(project);

        assertEquals(
                Set.of("no-such-job", "also-missing"),
                unresolved,
                "both missing names must be reported, so a typo is visible rather than merely " + "ineffective");
    }

    @Test
    @DisplayName("a mix of real and missing upstreams reports only the missing ones")
    void onlyMissingNamesAreReported(JenkinsRule j) throws Exception {
        j.createFreeStyleProject("real-upstream");

        FreeStyleProject project = j.createFreeStyleProject("mixed-deps");
        project.addProperty(new JobPriorityProperty("MEDIUM", "real-upstream, ghost-upstream"));

        Set<String> unresolved = DependencyGate.unresolvedUpstream(project);

        assertEquals(Set.of("ghost-upstream"), unresolved);
        assertFalse(unresolved.contains("real-upstream"));
    }

    @Test
    @DisplayName("a real but never-built upstream is not reported as unresolved")
    void existingUnbuiltUpstreamIsResolved(JenkinsRule j) throws Exception {
        // "Exists" is about the job being known to Jenkins, not about it having history. A brand
        // new upstream job is a perfectly valid dependency.
        j.createFreeStyleProject("never-built");

        FreeStyleProject project = j.createFreeStyleProject("depends-on-never-built");
        project.addProperty(new JobPriorityProperty("MEDIUM", "never-built"));

        assertTrue(DependencyGate.unresolvedUpstream(project).isEmpty());
        j.buildAndAssertSuccess(project);
    }

    @Test
    @DisplayName("a job with no declared dependencies reports nothing")
    void noDependenciesReportsNothing(JenkinsRule j) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject("no-deps");
        project.addProperty(new JobPriorityProperty("HIGH", ""));

        assertTrue(DependencyGate.unresolvedUpstream(project).isEmpty());
    }

    @Test
    @DisplayName("a job without the property at all reports nothing")
    void noPropertyReportsNothing(JenkinsRule j) throws Exception {
        assertTrue(DependencyGate.unresolvedUpstream(j.createFreeStyleProject("bare"))
                .isEmpty());
    }

    @Test
    @DisplayName("form validation rejects the unknown name at configuration time")
    void formValidationRejectsUnknownNames(JenkinsRule j) throws Exception {
        FreeStyleProject project = j.createFreeStyleProject("validated");
        JobPriorityProperty.DescriptorImpl descriptor =
                j.jenkins.getDescriptorByType(JobPriorityProperty.DescriptorImpl.class);

        assertEquals(
                hudson.util.FormValidation.Kind.ERROR,
                descriptor.doCheckDependsOn("no-such-job", project).kind,
                "catching the typo in the form is cheaper than reporting it at runtime");
        assertEquals(
                hudson.util.FormValidation.Kind.ERROR,
                descriptor.doCheckDependsOn("validated", project).kind,
                "a self-dependency must be rejected");
        assertEquals(hudson.util.FormValidation.Kind.OK, descriptor.doCheckDependsOn("", project).kind);
    }

    @Test
    @DisplayName("form validation rejects a dependency cycle")
    void formValidationRejectsCycles(JenkinsRule j) throws Exception {
        // a depends on b; proposing that b depend on a closes a cycle.
        FreeStyleProject a = j.createFreeStyleProject("cycle-a");
        FreeStyleProject b = j.createFreeStyleProject("cycle-b");
        a.addProperty(new JobPriorityProperty("MEDIUM", "cycle-b"));

        JobPriorityProperty.DescriptorImpl descriptor =
                j.jenkins.getDescriptorByType(JobPriorityProperty.DescriptorImpl.class);

        assertEquals(
                hudson.util.FormValidation.Kind.ERROR,
                descriptor.doCheckDependsOn("cycle-a", b).kind,
                "report Algorithm 6.3 line 6 rejects a cycle at submission");
    }

    @Test
    @DisplayName("a declared cycle never blocks the queue at runtime")
    void cycleDoesNotBlockAtRuntime(JenkinsRule j) throws Exception {
        // A cycle can still reach config.xml by hand. It is reported, never enforced: two jobs
        // each waiting for the other would hang both forever.
        j.jenkins.setNumExecutors(2);

        FreeStyleProject a = j.createFreeStyleProject("rt-cycle-a");
        FreeStyleProject b = j.createFreeStyleProject("rt-cycle-b");
        a.addProperty(new JobPriorityProperty("MEDIUM", "rt-cycle-b"));
        b.addProperty(new JobPriorityProperty("MEDIUM", "rt-cycle-a"));

        // Neither is queued or building yet, so neither gates the other, and both complete.
        j.buildAndAssertSuccess(a);
        j.buildAndAssertSuccess(b);
    }
}
