package io.jenkins.plugins.queueoptimizer.dependency;

import hudson.model.FreeStyleProject;
import hudson.tasks.BuildTrigger;
import io.jenkins.plugins.queueoptimizer.property.JobPriorityProperty;
import org.junit.Rule;
import org.junit.Test;
import org.jvnet.hudson.test.JenkinsRule;

import java.util.List;

import static org.junit.Assert.*;

/**
 * Integration tests for DependencyResolver.
 *
 * Unlike the other components, this class talks to Jenkins.get() directly,
 * so a real (in-memory) Jenkins instance via JenkinsRule is required to
 * create projects, wire up upstream/downstream relationships, and run builds.
 *
 * Covers both dependency sources:
 *   1. Native Jenkins "upstream project" triggers (BuildTrigger).
 *   2. The plugin's user-declared "Depends On" field (JobPriorityProperty).
 */
public class DependencyResolverTest {

    @Rule
    public JenkinsRule j = new JenkinsRule();

    private final DependencyResolver resolver = new DependencyResolver();

    // -----------------------------------------------------------------------
    // No dependencies
    // -----------------------------------------------------------------------

    @Test
    public void independentJobHasNoDependencies() throws Exception {
        FreeStyleProject job = j.createFreeStyleProject("standalone");

        assertTrue(resolver.getUpstreamDependencies(job.getFullName()).isEmpty());
        assertTrue(resolver.areDependenciesMet(job.getFullName()));
        assertEquals(50, resolver.calculateDependencyScore(job.getFullName()));
    }

    // -----------------------------------------------------------------------
    // Source 1: native Jenkins upstream triggers
    // -----------------------------------------------------------------------

    @Test
    public void nativeUpstreamTriggerIsDetected() throws Exception {
        FreeStyleProject upstream   = j.createFreeStyleProject("upstream-job");
        FreeStyleProject downstream = j.createFreeStyleProject("downstream-job");

        upstream.getPublishersList().add(new BuildTrigger("downstream-job", false));
        j.jenkins.rebuildDependencyGraph();

        assertEquals(List.of("upstream-job"),
                resolver.getUpstreamDependencies(downstream.getFullName()));
    }

    @Test
    public void nativeDependencyScoreReflectsUpstreamResult() throws Exception {
        FreeStyleProject upstream   = j.createFreeStyleProject("native-score-upstream");
        FreeStyleProject downstream = j.createFreeStyleProject("native-score-downstream");

        upstream.getPublishersList().add(new BuildTrigger("native-score-downstream", false));
        j.jenkins.rebuildDependencyGraph();

        // Upstream has never been built -> chain is blocked
        assertFalse(resolver.areDependenciesMet(downstream.getFullName()));
        assertEquals(20, resolver.calculateDependencyScore(downstream.getFullName()));

        j.buildAndAssertSuccess(upstream);

        // Upstream now succeeded -> chain is ready
        assertTrue(resolver.areDependenciesMet(downstream.getFullName()));
        assertEquals(80, resolver.calculateDependencyScore(downstream.getFullName()));
    }

    // -----------------------------------------------------------------------
    // Source 2: user-declared "Depends On" field
    // -----------------------------------------------------------------------

    @Test
    public void declaredDependsOnFieldIsDetected() throws Exception {
        j.createFreeStyleProject("declared-upstream");
        FreeStyleProject job = j.createFreeStyleProject("declared-dep-job");

        job.addProperty(new JobPriorityProperty("MEDIUM", "declared-upstream"));

        assertEquals(List.of("declared-upstream"),
                resolver.getUpstreamDependencies(job.getFullName()));
    }

    @Test
    public void declaredDependencyScoreReflectsUpstreamResult() throws Exception {
        FreeStyleProject upstream   = j.createFreeStyleProject("declared-score-upstream");
        FreeStyleProject downstream = j.createFreeStyleProject("declared-score-downstream");

        downstream.addProperty(new JobPriorityProperty("MEDIUM", "declared-score-upstream"));

        // Upstream has never been built -> chain is blocked
        assertFalse(resolver.areDependenciesMet(downstream.getFullName()));
        assertEquals(20, resolver.calculateDependencyScore(downstream.getFullName()));

        j.buildAndAssertSuccess(upstream);

        // Upstream now succeeded -> chain is ready
        assertTrue(resolver.areDependenciesMet(downstream.getFullName()));
        assertEquals(80, resolver.calculateDependencyScore(downstream.getFullName()));
    }

    // -----------------------------------------------------------------------
    // Combining both sources
    // -----------------------------------------------------------------------

    @Test
    public void combinesNativeAndDeclaredDependenciesWithoutDuplicates() throws Exception {
        FreeStyleProject upstream   = j.createFreeStyleProject("combo-upstream");
        j.createFreeStyleProject("combo-extra");
        FreeStyleProject downstream = j.createFreeStyleProject("combo-downstream");

        upstream.getPublishersList().add(new BuildTrigger("combo-downstream", false));
        j.jenkins.rebuildDependencyGraph();

        downstream.addProperty(new JobPriorityProperty("MEDIUM", "combo-upstream, combo-extra"));

        List<String> deps = resolver.getUpstreamDependencies(downstream.getFullName());

        assertEquals(2, deps.size());
        assertTrue(deps.contains("combo-upstream"));
        assertTrue(deps.contains("combo-extra"));
    }

    @Test
    public void declaredDuplicateOfNativeTriggerIsNotRepeated() throws Exception {
        FreeStyleProject upstream   = j.createFreeStyleProject("dup-upstream");
        FreeStyleProject downstream = j.createFreeStyleProject("dup-downstream");

        upstream.getPublishersList().add(new BuildTrigger("dup-downstream", false));
        j.jenkins.rebuildDependencyGraph();

        downstream.addProperty(new JobPriorityProperty("MEDIUM", "dup-upstream"));

        List<String> deps = resolver.getUpstreamDependencies(downstream.getFullName());

        assertEquals(List.of("dup-upstream"), deps);
    }
}
