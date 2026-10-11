package io.jenkins.plugins.queueoptimizer.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * The report's Appendix C worked example, asserted against the implementation.
 *
 * <p>Required by BUILD_PROMPT 4.3.10, and the most load-bearing test in the project. It is the
 * one thing standing between this plugin and Milestone 2's central failure, where the report
 * published {@code 0.5·U + 0.3·D + 0.2·T} while the code computed
 * {@code 0.5·urgency + 0.3·executionTime + 0.2·dependency} on a 0 to 100 scale with no aging.
 * Both existed for months. Neither ever contradicted the other, because nothing checked.
 *
 * <p>Tolerance is 0.001, as the specification requires.
 */
class AppendixCExampleTest {

    private static final double TOLERANCE = 0.001;

    private Map<String, ScoredJob> score() {
        return PriorityScoreCalculator.withReportDefaults().scoreAll(AppendixCFixture.queue()).stream()
                .collect(Collectors.toMap(ScoredJob::jobName, Function.identity()));
    }

    @Test
    @DisplayName("the four report jobs score 0.667, 0.650, 0.650 and 0.300")
    void effectiveScoresMatchTheReport() {
        Map<String, ScoredJob> scored = score();

        assertEquals(0.667, scored.get("deploy-payment-service").score(), TOLERANCE);
        assertEquals(0.650, scored.get("build-api").score(), TOLERANCE);
        assertEquals(0.650, scored.get("integration-tests-api").score(), TOLERANCE);
        assertEquals(0.300, scored.get("build-frontend").score(), TOLERANCE);
    }

    @Test
    @DisplayName("integration-tests-api scores 0.633 on its own merit and 0.650 after inheritance")
    void bothSidesOfTheGroupInheritanceAreAsserted() {
        // The report's Table 13.2 prints 0.633 in its Score column, then its prose says "Group G1
        // takes the maximum score of its members, 0.650". BUILD_PROMPT 4.3.10 requires 0.650.
        // Neither is wrong; they describe different stages. Asserting only one of them is what
        // left the ambiguity open in the first place, so this asserts both, and
        // scripts/report/appendix_c.py prints both columns. See docs/decisions.md D-004.
        ScoredJob consumer = score().get("integration-tests-api");

        assertEquals(0.633, consumer.ownScore(), TOLERANCE, "the report's printed table value");
        assertEquals(0.650, consumer.score(), TOLERANCE, "the effective value after inheritance");
        assertTrue(consumer.inheritedGroupScore(), "this job's score must come from its group");
    }

    @Test
    @DisplayName("every intermediate factor matches the report's table")
    void intermediateFactorsMatchTheReport() {
        Map<String, ScoredJob> scored = score();

        ScoredJob deploy = scored.get("deploy-payment-service");
        assertEquals(1.0, deploy.urgencyFactor(), TOLERANCE, "HIGH");
        assertEquals(0.0, deploy.dependencyFactor(), TOLERANCE, "independent");
        assertEquals(0.833, deploy.executionTimeFactor(), TOLERANCE, "1 - (3-2)/6");

        ScoredJob buildApi = scored.get("build-api");
        assertEquals(0.3, buildApi.urgencyFactor(), TOLERANCE, "LOW");
        assertEquals(1.0, buildApi.dependencyFactor(), TOLERANCE, "largest group");
        assertEquals(1.0, buildApi.executionTimeFactor(), TOLERANCE, "shortest estimate");

        ScoredJob integration = scored.get("integration-tests-api");
        assertEquals(0.6, integration.urgencyFactor(), TOLERANCE, "MEDIUM");
        assertEquals(1.0, integration.dependencyFactor(), TOLERANCE, "largest group");
        assertEquals(0.167, integration.executionTimeFactor(), TOLERANCE, "1 - (7-2)/6");

        ScoredJob frontend = scored.get("build-frontend");
        assertEquals(0.6, frontend.urgencyFactor(), TOLERANCE, "MEDIUM");
        assertEquals(0.0, frontend.dependencyFactor(), TOLERANCE, "independent");
        assertEquals(0.0, frontend.executionTimeFactor(), TOLERANCE, "longest estimate");
    }

    @Test
    @DisplayName("no aging has accumulated in the report's snapshot")
    void noAgingInTheWorkedExample() {
        score().values()
                .forEach(
                        job -> assertEquals(0.0, job.agingBonus(), TOLERANCE, job.jobName() + " should have no aging"));
    }

    @Test
    @DisplayName("the jobs dispatch in the report's order")
    void dispatchOrderMatchesTheReport() {
        List<String> actual = PriorityScoreCalculator.withReportDefaults().scoreAll(AppendixCFixture.queue()).stream()
                .sorted(PriorityScoreCalculator.compareForDispatch())
                .map(ScoredJob::jobName)
                .toList();

        // deploy-payment-service (0.667), then G1 as a unit ordered build-api before
        // integration-tests-api by Kahn, then build-frontend (0.300).
        assertEquals(AppendixCFixture.expectedDispatchOrder(), actual);
    }

    @Test
    @DisplayName("the group's producer is dispatched before its consumer despite a lower urgency")
    void producerRunsBeforeConsumerWithinTheGroup() {
        List<String> order = PriorityScoreCalculator.withReportDefaults().scoreAll(AppendixCFixture.queue()).stream()
                .sorted(PriorityScoreCalculator.compareForDispatch())
                .map(ScoredJob::jobName)
                .toList();

        // Both carry the inherited 0.650, so only the topological rank separates them. A LOW job
        // running before a MEDIUM one is the safeguard the report calls out: build-api overtakes
        // on the group's merit, not its own.
        assertTrue(
                order.indexOf("build-api") < order.indexOf("integration-tests-api"),
                "the producer must run first, or the consumer has nothing to consume");
    }

    @Test
    @DisplayName("the HIGH deployment overtakes the eight-minute MEDIUM build it arrived behind")
    void theExampleActuallyDemonstratesTheImprovement() {
        // Under FIFO, arrival order is build-frontend, build-api, integration-tests-api,
        // deploy-payment-service, so the HIGH deployment waits behind everything. If this ever
        // stops holding, the example no longer shows what the report claims it shows.
        List<String> order = PriorityScoreCalculator.withReportDefaults().scoreAll(AppendixCFixture.queue()).stream()
                .sorted(PriorityScoreCalculator.compareForDispatch())
                .map(ScoredJob::jobName)
                .toList();

        assertEquals("deploy-payment-service", order.get(0));
        assertTrue(order.indexOf("deploy-payment-service") < order.indexOf("build-frontend"));
    }

    @Test
    @DisplayName("the weights are the report's, not Milestone 2's transposed pair")
    void weightsAreNotTransposed() {
        // Milestone 2 weighted execution time 0.3 and dependency 0.2, the wrong way round. That
        // survived because no test ever compared the code against the published formula. This is
        // that comparison, made concrete: with the weights transposed, build-api's base score
        // would be 0.15 + 0.2*1.0 + 0.3*1.0 = 0.650 as well, so the totals alone cannot catch it.
        // The factors must be checked against their own weights.
        ScoredJob integration = score().get("integration-tests-api");

        double asReported = 0.5 * integration.urgencyFactor()
                + 0.3 * integration.dependencyFactor()
                + 0.2 * integration.executionTimeFactor();
        double asMilestone2 = 0.5 * integration.urgencyFactor()
                + 0.3 * integration.executionTimeFactor()
                + 0.2 * integration.dependencyFactor();

        assertEquals(asReported, integration.baseScore(), TOLERANCE);
        assertFalse(
                Math.abs(asMilestone2 - integration.baseScore()) < TOLERANCE,
                "the Milestone 2 weighting must not reproduce this score, or the test proves nothing");
    }
}
