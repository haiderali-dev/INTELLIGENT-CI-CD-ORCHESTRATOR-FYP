package io.jenkins.plugins.queueoptimizer.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;

/**
 * Required by BUILD_PROMPT 4.3.10: 0.05 per 5 minutes, capped at 0.15.
 *
 * <p>Aging is the plugin's only defence against starvation, and Milestone 2 shipped without it.
 * The cost is in the numbers: its LOW band waited a mean of 233 s against a 16 s FIFO baseline,
 * a 1366 % regression, because nothing ever lifted a LOW job once HIGH work kept arriving. See
 * {@code docs/m2-baseline.md} section 3.1.
 */
class AgingTest {

    private static final double TOLERANCE = 0.001;
    private static final long MINUTE = 60_000L;

    private static double agingFor(long waitMillis) {
        return PriorityScoreCalculator.withReportDefaults()
                .scoreAll(List.of(ScoreInput.independent(1, "job", PriorityLevel.LOW, MINUTE, waitMillis)))
                .get(0)
                .agingBonus();
    }

    @ParameterizedTest(name = "{0} minutes waited gives a bonus of {1}")
    @CsvSource({
        "0,    0.00",
        "1,    0.00",
        "4,    0.00", // still inside the first interval
        "5,    0.05", // first step
        "9,    0.05",
        "10,   0.10", // second step
        "14,   0.10",
        "15,   0.15", // third step, which is also the cap
        "20,   0.15", // capped
        "60,   0.15",
        "1440, 0.15" // a full day, still capped
    })
    @DisplayName("the bonus steps every 5 minutes and stops at 0.15")
    void bonusStepsAndCaps(long waitMinutes, double expected) {
        assertEquals(expected, agingFor(waitMinutes * MINUTE), TOLERANCE);
    }

    @Test
    @DisplayName("the bonus is a step function, not a smooth ramp")
    void bonusIsAStepFunction() {
        // The report specifies floor(waitMinutes / 5), so everything inside an interval scores
        // identically. A smooth ramp would be a different algorithm from the published one.
        assertEquals(agingFor(5 * MINUTE), agingFor(9 * MINUTE), TOLERANCE);
        assertTrue(agingFor(10 * MINUTE) > agingFor(9 * MINUTE), "the interval boundary must step");
    }

    @Test
    @DisplayName("a negative or zero wait earns nothing")
    void noBonusWithoutWaiting() {
        assertEquals(0.0, agingFor(0), TOLERANCE);
        assertEquals(0.0, agingFor(-1000), TOLERANCE);
    }

    @Test
    @DisplayName("aging adds to the base score rather than replacing it")
    void agingAddsToBase() {
        ScoredJob aged = PriorityScoreCalculator.withReportDefaults()
                .scoreAll(List.of(ScoreInput.independent(1, "waited", PriorityLevel.LOW, MINUTE, 15 * MINUTE)))
                .get(0);

        assertEquals(0.15, aged.agingBonus(), TOLERANCE);
        assertEquals(aged.baseScore() + 0.15, aged.score(), TOLERANCE);
    }

    @Test
    @DisplayName("a fully aged LOW job overtakes a freshly queued MEDIUM job")
    void agingActuallyPreventsStarvation() {
        // This is the behaviour the whole mechanism exists for. An independent LOW job with a
        // neutral estimate scores 0.15 + 0.1 = 0.25 and rises to 0.40 at the cap; a fresh MEDIUM
        // scores 0.30 + 0.1 = 0.40 ... so the cap alone is not quite enough to overtake on equal
        // estimates, and the LOW job also needs the shorter-job advantage. Asserting the real
        // relationship rather than a hoped-for one.
        List<ScoredJob> scored = PriorityScoreCalculator.withReportDefaults()
                .scoreAll(List.of(
                        ScoreInput.independent(1, "starved-low", PriorityLevel.LOW, 1 * MINUTE, 15 * MINUTE),
                        ScoreInput.independent(2, "fresh-medium", PriorityLevel.MEDIUM, 9 * MINUTE, 0)));

        ScoredJob low = scored.stream()
                .filter(j -> j.jobName().equals("starved-low"))
                .findFirst()
                .orElseThrow();
        ScoredJob medium = scored.stream()
                .filter(j -> j.jobName().equals("fresh-medium"))
                .findFirst()
                .orElseThrow();

        assertTrue(
                low.score() > medium.score(),
                "a LOW job waiting 15 minutes must eventually overtake fresh MEDIUM work; " + "low=" + low.score()
                        + " medium=" + medium.score());
    }

    @Test
    @DisplayName("aging never lets a LOW job overtake a HIGH job of equal estimate")
    void agingDoesNotInvertUrgencyEntirely() {
        // The cap exists so aging cannot defeat urgency outright. With equal estimates a LOW job
        // reaches 0.15 + 0.1 + 0.15 = 0.40 while HIGH sits at 0.5 + 0.1 = 0.60.
        List<ScoredJob> scored = PriorityScoreCalculator.withReportDefaults()
                .scoreAll(List.of(
                        ScoreInput.independent(1, "old-low", PriorityLevel.LOW, 5 * MINUTE, 600 * MINUTE),
                        ScoreInput.independent(2, "new-high", PriorityLevel.HIGH, 5 * MINUTE, 0)));

        ScoredJob low = scored.stream()
                .filter(j -> j.jobName().equals("old-low"))
                .findFirst()
                .orElseThrow();
        ScoredJob high = scored.stream()
                .filter(j -> j.jobName().equals("new-high"))
                .findFirst()
                .orElseThrow();

        assertTrue(high.score() > low.score(), "the cap must keep urgency decisive");
    }

    @Test
    @DisplayName("a custom aging configuration is honoured")
    void customConfigurationIsUsed() {
        // The experiment's aging-ablation arm turns the bonus off entirely, so this must be
        // driven by configuration rather than hardcoded.
        PriorityScoreCalculator noAging = new PriorityScoreCalculator(0.5, 0.3, 0.2, 0.0, 5, 0.0);
        ScoredJob job = noAging.scoreAll(
                        List.of(ScoreInput.independent(1, "job", PriorityLevel.LOW, MINUTE, 60 * MINUTE)))
                .get(0);

        assertEquals(0.0, job.agingBonus(), TOLERANCE, "the ablation arm must see no aging at all");
    }
}
