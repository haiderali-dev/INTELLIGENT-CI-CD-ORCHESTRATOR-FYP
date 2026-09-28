package io.jenkins.plugins.queueoptimizer.scoring;

import io.jenkins.plugins.queueoptimizer.dependency.DependencyResolver;
import io.jenkins.plugins.queueoptimizer.estimation.ExecutionTimeEstimator;
import io.jenkins.plugins.queueoptimizer.model.JobPriority;
import io.jenkins.plugins.queueoptimizer.model.ScoredJob;
import org.junit.Before;
import org.junit.Test;

import java.util.List;

import static org.junit.Assert.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/**
 * Unit tests for PriorityScoreCalculator.
 *
 * Tests use calculateByName() — the testable core method that accepts plain
 * String job names instead of Queue.BuildableItem. This means zero dependency
 * on Jenkins runtime classes; standard Mockito is sufficient.
 */
public class PriorityScoreCalculatorTest {

    private ExecutionTimeEstimator  estimator;
    private DependencyResolver      resolver;
    private PriorityScoreCalculator calculator;

    @Before
    public void setUp() {
        estimator  = mock(ExecutionTimeEstimator.class);
        resolver   = mock(DependencyResolver.class);
        calculator = new PriorityScoreCalculator(estimator, resolver);

        // Sensible defaults — individual tests override as needed
        when(estimator.estimate(anyString())).thenReturn(60.0);
        when(resolver.calculateDependencyScore(anyString())).thenReturn(50);
        when(resolver.getUpstreamDependencies(anyString())).thenReturn(List.of());
    }

    // -----------------------------------------------------------------------
    // Priority ordering
    // -----------------------------------------------------------------------

    @Test
    public void highPriorityScoresAboveMedium() {
        ScoredJob high   = score("high-job",   JobPriority.HIGH,   List.of("high-job", "med-job"));
        ScoredJob medium = score("med-job",    JobPriority.MEDIUM, List.of("high-job", "med-job"));

        assertTrue("HIGH must score above MEDIUM",
                high.getPriorityScore() > medium.getPriorityScore());
    }

    @Test
    public void mediumPriorityScoresAboveLow() {
        ScoredJob medium = score("med-job", JobPriority.MEDIUM, List.of("med-job", "low-job"));
        ScoredJob low    = score("low-job", JobPriority.LOW,    List.of("med-job", "low-job"));

        assertTrue("MEDIUM must score above LOW",
                medium.getPriorityScore() > low.getPriorityScore());
    }

    @Test
    public void highPriorityScoresAboveLow() {
        ScoredJob high = score("h", JobPriority.HIGH, List.of("h", "l"));
        ScoredJob low  = score("l", JobPriority.LOW,  List.of("h", "l"));
        assertTrue(high.getPriorityScore() > low.getPriorityScore());
    }

    // -----------------------------------------------------------------------
    // Execution time contribution (Shortest Job First)
    // -----------------------------------------------------------------------

    @Test
    public void shorterJobScoresHigherWithSamePriority() {
        when(estimator.estimate("short-job")).thenReturn(10.0);
        when(estimator.estimate("long-job")).thenReturn(200.0);

        ScoredJob shortJob = score("short-job", JobPriority.MEDIUM, List.of("short-job", "long-job"));
        ScoredJob longJob  = score("long-job",  JobPriority.MEDIUM, List.of("short-job", "long-job"));

        assertTrue("Shorter job must score higher (SJF principle)",
                shortJob.getPriorityScore() > longJob.getPriorityScore());
    }

    @Test
    public void singleJobInQueueGetsNeutralExecTimeScore() {
        // When a job is the only one in the queue, maxTime == estimatedTime
        // → execTimeScore = 100*(1 - 1) = 0 (neutral)
        ScoredJob result = score("solo-job", JobPriority.HIGH, List.of("solo-job"));
        // Score should still be positive due to urgency component
        assertTrue(result.getPriorityScore() > 0);
    }

    // -----------------------------------------------------------------------
    // Score is always within 0–100
    // -----------------------------------------------------------------------

    @Test
    public void scoreIsAlwaysInRange() {
        for (JobPriority p : JobPriority.values()) {
            ScoredJob result = score("test-job", p, List.of("test-job"));
            assertTrue("Score should be >= 0",  result.getPriorityScore() >= 0);
            assertTrue("Score should be <= 100", result.getPriorityScore() <= 100);
        }
    }

    // -----------------------------------------------------------------------
    // ScoredJob carries correct metadata
    // -----------------------------------------------------------------------

    @Test
    public void scoredJobCarriesEstimatedDuration() {
        when(estimator.estimate("my-job")).thenReturn(42.0);
        ScoredJob result = score("my-job", JobPriority.MEDIUM, List.of("my-job"));
        assertEquals(42.0, result.getEstimatedDurationSeconds(), 0.001);
    }

    @Test
    public void scoredJobCarriesCorrectJobName() {
        ScoredJob result = score("my-named-job", JobPriority.LOW, List.of("my-named-job"));
        assertEquals("my-named-job", result.getJobName());
    }

    @Test
    public void scoredJobReportsDependencyFlag() {
        when(resolver.getUpstreamDependencies("dep-job")).thenReturn(List.of("upstream"));
        ScoredJob result = score("dep-job", JobPriority.HIGH, List.of("dep-job"));
        assertTrue(result.hasDependency());
    }

    @Test
    public void independentJobReportsNoDependency() {
        when(resolver.getUpstreamDependencies("standalone")).thenReturn(List.of());
        ScoredJob result = score("standalone", JobPriority.MEDIUM, List.of("standalone"));
        assertFalse(result.hasDependency());
    }

    // -----------------------------------------------------------------------
    // Helper — calls the package-accessible testable method (null item = test path)
    // -----------------------------------------------------------------------

    private ScoredJob score(String jobName, JobPriority priority, List<String> peers) {
        return calculator.calculateByName(null, jobName, priority, peers);
    }
}
