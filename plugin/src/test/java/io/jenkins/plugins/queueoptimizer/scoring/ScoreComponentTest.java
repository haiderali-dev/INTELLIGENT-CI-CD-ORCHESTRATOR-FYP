package io.jenkins.plugins.queueoptimizer.scoring;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.jenkins.plugins.queueoptimizer.model.PriorityLevel;
import java.util.List;
import java.util.Map;
import java.util.OptionalLong;
import java.util.function.Function;
import java.util.stream.Collectors;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * Required by BUILD_PROMPT 4.3.10: U, D, T, aging and group inheritance, including the
 * {@code estMax == estMin} and UNKNOWN edge cases.
 *
 * <p>{@link AppendixCExampleTest} pins the formula to the report's one worked example. This pins
 * the behaviour around it, particularly the degenerate inputs the example never exercises, which
 * are where a scoring bug actually hides.
 */
class ScoreComponentTest {

    private static final double TOLERANCE = 0.001;
    private static final long MINUTE = 60_000L;

    private static Map<String, ScoredJob> score(List<ScoreInput> queue) {
        return PriorityScoreCalculator.withReportDefaults().scoreAll(queue).stream()
                .collect(Collectors.toMap(ScoredJob::jobName, Function.identity()));
    }

    @Nested
    @DisplayName("U, the urgency factor")
    class Urgency {

        @Test
        @DisplayName("maps the three levels to 1.0, 0.6 and 0.3")
        void levelsMapToNormalisedValues() {
            assertEquals(1.0, PriorityLevel.HIGH.getUrgency(), TOLERANCE);
            assertEquals(0.6, PriorityLevel.MEDIUM.getUrgency(), TOLERANCE);
            assertEquals(0.3, PriorityLevel.LOW.getUrgency(), TOLERANCE);
        }

        @Test
        @DisplayName("an unreadable level degrades to MEDIUM rather than failing")
        void unreadableLevelDegradesToMedium() {
            // A job config is user-editable XML and may hold anything, including a value written
            // by an older plugin. It must never break queue maintenance.
            assertEquals(PriorityLevel.MEDIUM, PriorityLevel.fromString(null));
            assertEquals(PriorityLevel.MEDIUM, PriorityLevel.fromString(""));
            assertEquals(PriorityLevel.MEDIUM, PriorityLevel.fromString("  "));
            assertEquals(PriorityLevel.MEDIUM, PriorityLevel.fromString("URGENT"));
            assertEquals(PriorityLevel.HIGH, PriorityLevel.fromString("high"));
            assertEquals(PriorityLevel.HIGH, PriorityLevel.fromString(" HIGH "));
        }

        @Test
        @DisplayName("an independent LOW job cannot outrank an independent HIGH job")
        void lowCannotOvertakeHighOnItsOwn() {
            // The report states this bound: a LOW job maxes out at 0.5 + aging when independent,
            // while a HIGH job starts at 0.5. Without aging, urgency is decisive.
            Map<String, ScoredJob> scored = score(List.of(
                    ScoreInput.independent(1, "low-fast", PriorityLevel.LOW, 1 * MINUTE, 0),
                    ScoreInput.independent(2, "high-slow", PriorityLevel.HIGH, 9 * MINUTE, 0)));

            assertTrue(
                    scored.get("high-slow").score() > scored.get("low-fast").score(),
                    "the shortest possible LOW job must not overtake the longest HIGH job");
        }
    }

    @Nested
    @DisplayName("D, the dependency factor")
    class Dependency {

        @Test
        @DisplayName("is 0 for an independent job")
        void independentScoresZero() {
            Map<String, ScoredJob> scored = score(List.of(
                    ScoreInput.independent(1, "solo", PriorityLevel.MEDIUM, MINUTE, 0),
                    new ScoreInput(2, "g1", PriorityLevel.MEDIUM, "G", 3, 0, OptionalLong.of(MINUTE), 0, 2),
                    new ScoreInput(3, "g2", PriorityLevel.MEDIUM, "G", 3, 1, OptionalLong.of(MINUTE), 0, 3),
                    new ScoreInput(4, "g3", PriorityLevel.MEDIUM, "G", 3, 2, OptionalLong.of(MINUTE), 0, 4)));

            assertEquals(0.0, scored.get("solo").dependencyFactor(), TOLERANCE);
        }

        @Test
        @DisplayName("is 1 for a member of the largest group")
        void largestGroupScoresOne() {
            Map<String, ScoredJob> scored = score(List.of(
                    new ScoreInput(1, "big1", PriorityLevel.MEDIUM, "BIG", 3, 0, OptionalLong.of(MINUTE), 0, 1),
                    new ScoreInput(2, "big2", PriorityLevel.MEDIUM, "BIG", 3, 1, OptionalLong.of(MINUTE), 0, 2),
                    new ScoreInput(3, "big3", PriorityLevel.MEDIUM, "BIG", 3, 2, OptionalLong.of(MINUTE), 0, 3)));

            assertEquals(1.0, scored.get("big1").dependencyFactor(), TOLERANCE);
        }

        @Test
        @DisplayName("scales linearly between group sizes")
        void scalesBetweenGroupSizes() {
            // maxGroupSize 5, so a group of 3 scores (3-1)/(5-1) = 0.5.
            List<ScoreInput> queue = new java.util.ArrayList<>();
            for (int i = 0; i < 5; i++) {
                queue.add(new ScoreInput(
                        100 + i, "big" + i, PriorityLevel.MEDIUM, "BIG", 5, i, OptionalLong.of(MINUTE), 0, 100 + i));
            }
            for (int i = 0; i < 3; i++) {
                queue.add(new ScoreInput(
                        200 + i, "mid" + i, PriorityLevel.MEDIUM, "MID", 3, i, OptionalLong.of(MINUTE), 0, 200 + i));
            }

            assertEquals(0.5, score(queue).get("mid0").dependencyFactor(), TOLERANCE);
        }

        @Test
        @DisplayName("is 0 for everyone when no group has more than one member")
        void allSingletonsScoreZero() {
            // Guards the maxGroupSize == 1 division. D must not become a constant offset on a
            // queue of independent jobs, which is the common case.
            Map<String, ScoredJob> scored = score(List.of(
                    ScoreInput.independent(1, "a", PriorityLevel.MEDIUM, MINUTE, 0),
                    ScoreInput.independent(2, "b", PriorityLevel.MEDIUM, MINUTE, 0)));

            scored.values().forEach(job ->
                    assertEquals(0.0, job.dependencyFactor(), TOLERANCE, job.jobName()));
        }
    }

    @Nested
    @DisplayName("T, the execution-time factor")
    class ExecutionTime {

        @Test
        @DisplayName("the shortest job scores 1 and the longest scores 0")
        void spansTheRange() {
            Map<String, ScoredJob> scored = score(List.of(
                    ScoreInput.independent(1, "short", PriorityLevel.MEDIUM, 2 * MINUTE, 0),
                    ScoreInput.independent(2, "long", PriorityLevel.MEDIUM, 8 * MINUTE, 0)));

            assertEquals(1.0, scored.get("short").executionTimeFactor(), TOLERANCE);
            assertEquals(0.0, scored.get("long").executionTimeFactor(), TOLERANCE);
        }

        @Test
        @DisplayName("an UNKNOWN estimate takes the neutral 0.5")
        void unknownEstimateIsNeutral() {
            // A brand new job is neither punished nor favoured. Treating unknown as zero would
            // make an unmeasured job look like the slowest in the queue.
            Map<String, ScoredJob> scored = score(List.of(
                    ScoreInput.independent(1, "known-fast", PriorityLevel.MEDIUM, 1 * MINUTE, 0),
                    ScoreInput.independent(2, "known-slow", PriorityLevel.MEDIUM, 9 * MINUTE, 0),
                    ScoreInput.independentUnknownEstimate(3, "brand-new", PriorityLevel.MEDIUM, 0)));

            ScoredJob unknown = scored.get("brand-new");
            assertEquals(0.5, unknown.executionTimeFactor(), TOLERANCE);
            assertTrue(unknown.hasUnknownEstimate());
        }

        @Test
        @DisplayName("estMax == estMin gives everyone the neutral 0.5 instead of dividing by zero")
        void identicalEstimatesAreNeutral() {
            // Exactly what the experiment's warm-up phase produces: a queue of jobs with the same
            // measured duration. A naive implementation divides by zero here.
            Map<String, ScoredJob> scored = score(List.of(
                    ScoreInput.independent(1, "a", PriorityLevel.MEDIUM, 5 * MINUTE, 0),
                    ScoreInput.independent(2, "b", PriorityLevel.MEDIUM, 5 * MINUTE, 0),
                    ScoreInput.independent(3, "c", PriorityLevel.MEDIUM, 5 * MINUTE, 0)));

            scored.values().forEach(job -> {
                assertEquals(0.5, job.executionTimeFactor(), TOLERANCE, job.jobName());
                assertTrue(Double.isFinite(job.score()), job.jobName() + " produced a non-finite score");
            });
        }

        @Test
        @DisplayName("a queue where nothing has an estimate is entirely neutral")
        void noEstimatesAnywhere() {
            Map<String, ScoredJob> scored = score(List.of(
                    ScoreInput.independentUnknownEstimate(1, "a", PriorityLevel.MEDIUM, 0),
                    ScoreInput.independentUnknownEstimate(2, "b", PriorityLevel.HIGH, 0)));

            scored.values().forEach(job ->
                    assertEquals(0.5, job.executionTimeFactor(), TOLERANCE, job.jobName()));
            assertTrue(scored.get("b").score() > scored.get("a").score(), "urgency still separates them");
        }

        @Test
        @DisplayName("a single queued job takes the neutral factor")
        void singleJobIsNeutral() {
            Map<String, ScoredJob> scored =
                    score(List.of(ScoreInput.independent(1, "only", PriorityLevel.MEDIUM, 5 * MINUTE, 0)));

            assertEquals(0.5, scored.get("only").executionTimeFactor(), TOLERANCE);
        }
    }

    @Nested
    @DisplayName("group inheritance")
    class GroupInheritance {

        @Test
        @DisplayName("every member of a group takes the group's best score")
        void membersTakeTheBestScore() {
            Map<String, ScoredJob> scored = score(List.of(
                    new ScoreInput(1, "weak", PriorityLevel.LOW, "G", 2, 0, OptionalLong.of(5 * MINUTE), 0, 1),
                    new ScoreInput(2, "strong", PriorityLevel.HIGH, "G", 2, 1, OptionalLong.of(5 * MINUTE), 0, 2)));

            assertEquals(scored.get("strong").score(), scored.get("weak").score(), TOLERANCE);
            assertTrue(scored.get("weak").inheritedGroupScore());
            assertFalse(scored.get("strong").inheritedGroupScore(), "the best member inherits nothing");
        }

        @Test
        @DisplayName("inheritance keeps the member's own score visible")
        void ownScoreSurvivesInheritance() {
            // The API and the score bar need both numbers: what this job earned, and what its
            // group lifted it to. Overwriting the first would make the ranking unexplainable.
            Map<String, ScoredJob> scored = score(List.of(
                    new ScoreInput(1, "weak", PriorityLevel.LOW, "G", 2, 0, OptionalLong.of(5 * MINUTE), 0, 1),
                    new ScoreInput(2, "strong", PriorityLevel.HIGH, "G", 2, 1, OptionalLong.of(5 * MINUTE), 0, 2)));

            ScoredJob weak = scored.get("weak");
            assertTrue(weak.ownScore() < weak.score(), "own score must stay below the inherited one");
            assertEquals(weak.baseScore() + weak.agingBonus(), weak.ownScore(), TOLERANCE);
        }

        @Test
        @DisplayName("a single-member group inherits nothing")
        void singletonGroupDoesNotInherit() {
            Map<String, ScoredJob> scored =
                    score(List.of(ScoreInput.independent(1, "solo", PriorityLevel.LOW, MINUTE, 0)));

            assertFalse(scored.get("solo").inheritedGroupScore());
            assertEquals(scored.get("solo").ownScore(), scored.get("solo").score(), TOLERANCE);
        }

        @Test
        @DisplayName("separate groups do not lift each other")
        void groupsAreIndependent() {
            Map<String, ScoredJob> scored = score(List.of(
                    new ScoreInput(1, "a1", PriorityLevel.LOW, "A", 2, 0, OptionalLong.of(5 * MINUTE), 0, 1),
                    new ScoreInput(2, "a2", PriorityLevel.LOW, "A", 2, 1, OptionalLong.of(5 * MINUTE), 0, 2),
                    new ScoreInput(3, "b1", PriorityLevel.HIGH, "B", 2, 0, OptionalLong.of(5 * MINUTE), 0, 3),
                    new ScoreInput(4, "b2", PriorityLevel.HIGH, "B", 2, 1, OptionalLong.of(5 * MINUTE), 0, 4)));

            assertTrue(
                    scored.get("b1").score() > scored.get("a1").score(),
                    "a HIGH group must not lift an unrelated LOW group");
        }
    }

    @Nested
    @DisplayName("dispatch ordering")
    class Ordering {

        @Test
        @DisplayName("ties fall to the earlier enqueue time, then the lower item id")
        void tiesAreBrokenDeterministically() {
            // Without a total order, repeated heap rebuilds swap which of several tied jobs sits
            // at the root and no item is ever consistently the top. Milestone 2 hit exactly this.
            List<ScoredJob> ordered = PriorityScoreCalculator.withReportDefaults()
                    .scoreAll(List.of(
                            new ScoreInput(9, "later", PriorityLevel.MEDIUM, "s9", 1, 0, OptionalLong.of(MINUTE), 0, 200),
                            new ScoreInput(3, "earlier", PriorityLevel.MEDIUM, "s3", 1, 0, OptionalLong.of(MINUTE), 0, 100)))
                    .stream()
                    .sorted(PriorityScoreCalculator.compareForDispatch())
                    .toList();

            assertEquals("earlier", ordered.get(0).jobName());
        }

        @Test
        @DisplayName("the comparator is a total order, so sorting is stable across runs")
        void comparatorIsTotal() {
            List<ScoreInput> queue = List.of(
                    new ScoreInput(1, "a", PriorityLevel.MEDIUM, "s1", 1, 0, OptionalLong.of(MINUTE), 0, 50),
                    new ScoreInput(2, "b", PriorityLevel.MEDIUM, "s2", 1, 0, OptionalLong.of(MINUTE), 0, 50),
                    new ScoreInput(3, "c", PriorityLevel.MEDIUM, "s3", 1, 0, OptionalLong.of(MINUTE), 0, 50));

            List<String> first = PriorityScoreCalculator.withReportDefaults().scoreAll(queue).stream()
                    .sorted(PriorityScoreCalculator.compareForDispatch())
                    .map(ScoredJob::jobName)
                    .toList();
            List<String> second = PriorityScoreCalculator.withReportDefaults().scoreAll(queue).stream()
                    .sorted(PriorityScoreCalculator.compareForDispatch())
                    .map(ScoredJob::jobName)
                    .toList();

            assertEquals(first, second, "identical input must produce identical order");
            assertEquals(List.of("a", "b", "c"), first);
        }
    }

    @Test
    @DisplayName("an empty queue scores to an empty list")
    void emptyQueue() {
        assertTrue(PriorityScoreCalculator.withReportDefaults().scoreAll(List.of()).isEmpty());
    }
}
