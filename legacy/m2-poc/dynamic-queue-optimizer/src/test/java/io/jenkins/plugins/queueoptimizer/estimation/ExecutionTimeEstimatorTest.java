package io.jenkins.plugins.queueoptimizer.estimation;

import org.junit.Test;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import static org.junit.Assert.*;
import static org.mockito.Mockito.*;

/**
 * Unit tests for ExecutionTimeEstimator.
 * Uses Mockito to stub BuildHistoryAnalyzer so no Jenkins instance is needed.
 */
public class ExecutionTimeEstimatorTest {

    private static final String JOB = "my-test-job";

    // -----------------------------------------------------------------------
    // Strategy 1: own history
    // -----------------------------------------------------------------------

    @Test
    public void usesWeightedAverageWhenOwnHistoryExists() {
        BuildHistoryAnalyzer analyzer = mock(BuildHistoryAnalyzer.class);
        // 3 builds (newest first): 60s, 40s, 50s
        when(analyzer.getRecentSuccessfulDurations(JOB))
                .thenReturn(Arrays.asList(60.0, 40.0, 50.0));

        double estimate = new ExecutionTimeEstimator(analyzer).estimate(JOB);

        // WMA with weights [0.40, 0.30, 0.15]:
        //   (60*0.40 + 40*0.30 + 50*0.15) / (0.40+0.30+0.15)
        //   = (24 + 12 + 7.5) / 0.85 = 43.5 / 0.85 ≈ 51.18
        assertTrue("Estimate should be between 40 and 65", estimate >= 40 && estimate <= 65);
        verify(analyzer).getRecentSuccessfulDurations(JOB);
    }

    @Test
    public void recentBuildsWeightedMoreThanOldOnes() {
        BuildHistoryAnalyzer analyzer = mock(BuildHistoryAnalyzer.class);
        // Recent builds are fast (10s), old build is slow (200s)
        when(analyzer.getRecentSuccessfulDurations(JOB))
                .thenReturn(Arrays.asList(10.0, 10.0, 200.0));

        double estimate = new ExecutionTimeEstimator(analyzer).estimate(JOB);

        // Plain average would be ~73s; weighted average should be much closer to 10s
        assertTrue("Weighted estimate should favour recent fast builds", estimate < 73.0);
    }

    // -----------------------------------------------------------------------
    // Strategy 2: similar jobs fallback
    // -----------------------------------------------------------------------

    @Test
    public void fallsBackToSimilarJobsWhenOwnHistoryThin() {
        BuildHistoryAnalyzer analyzer = mock(BuildHistoryAnalyzer.class);

        // Own history: only 1 build (below threshold of 3)
        when(analyzer.getRecentSuccessfulDurations(JOB))
                .thenReturn(List.of(30.0));

        // Similar job found with 120s history
        when(analyzer.findSimilarJobNames(JOB))
                .thenReturn(List.of("similar-job"));
        when(analyzer.getRecentSuccessfulDurations("similar-job"))
                .thenReturn(List.of(120.0));

        double estimate = new ExecutionTimeEstimator(analyzer).estimate(JOB);

        assertEquals(120.0, estimate, 0.001);
    }

    // -----------------------------------------------------------------------
    // Strategy 3: global average fallback
    // -----------------------------------------------------------------------

    @Test
    public void fallsBackToGlobalAverageWhenNoHistory() {
        BuildHistoryAnalyzer analyzer = mock(BuildHistoryAnalyzer.class);

        when(analyzer.getRecentSuccessfulDurations(JOB))
                .thenReturn(Collections.emptyList());
        when(analyzer.findSimilarJobNames(JOB))
                .thenReturn(Collections.emptyList());
        when(analyzer.getGlobalAverageDuration()).thenReturn(75.0);

        double estimate = new ExecutionTimeEstimator(analyzer).estimate(JOB);

        assertEquals(75.0, estimate, 0.001);
        verify(analyzer).getGlobalAverageDuration();
    }

    @Test
    public void returnsDefaultWhenEverythingEmpty() {
        BuildHistoryAnalyzer analyzer = mock(BuildHistoryAnalyzer.class);

        when(analyzer.getRecentSuccessfulDurations(anyString()))
                .thenReturn(Collections.emptyList());
        when(analyzer.findSimilarJobNames(anyString()))
                .thenReturn(Collections.emptyList());
        when(analyzer.getGlobalAverageDuration()).thenReturn(60.0); // default in analyzer

        double estimate = new ExecutionTimeEstimator(analyzer).estimate("brand-new-job");

        assertEquals(60.0, estimate, 0.001);
    }
}
