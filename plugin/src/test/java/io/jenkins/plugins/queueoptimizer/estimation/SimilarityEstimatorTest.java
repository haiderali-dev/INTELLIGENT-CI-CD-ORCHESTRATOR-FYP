package io.jenkins.plugins.queueoptimizer.estimation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import java.util.OptionalLong;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

/**
 * Required by BUILD_PROMPT 4.3.10: Jaccard features, threshold, top-k, decay and UNKNOWN.
 *
 * <p>Report Algorithm 6.4. Plain Java throughout, which is the reason the similarity maths was kept
 * out of the Jenkins-facing {@link BuildHistoryService}.
 */
class SimilarityEstimatorTest {

    private static final double TOLERANCE = 0.001;
    private static final long SECOND = 1000L;

    /** A target job with no parameters, on the linux label. */
    private static BuildRecord target(String name) {
        return BuildRecord.of(name, Map.of(), "linux", 0L, 0.0);
    }

    private static BuildRecord history(String name, String label, long durationMillis, double ageDays) {
        return BuildRecord.of(name, Map.of(), label, durationMillis, ageDays);
    }

    @Nested
    @DisplayName("Jaccard index")
    class Jaccard {

        @Test
        @DisplayName("identical sets score 1 and disjoint sets score 0")
        void identicalAndDisjoint() {
            assertEquals(1.0, SimilarityEstimator.jaccard(Set.of("a", "b"), Set.of("a", "b")), TOLERANCE);
            assertEquals(0.0, SimilarityEstimator.jaccard(Set.of("a"), Set.of("b")), TOLERANCE);
        }

        @Test
        @DisplayName("partial overlap is intersection over union")
        void partialOverlap() {
            // {a,b,c} vs {b,c,d}: intersection 2, union 4.
            assertEquals(0.5, SimilarityEstimator.jaccard(Set.of("a", "b", "c"), Set.of("b", "c", "d")), TOLERANCE);
        }

        @Test
        @DisplayName("two empty sets count as identical")
        void bothEmptyIsAMatch() {
            // The right reading for parameters: "neither build takes any" is a genuine match, not
            // missing information. Otherwise an unparameterised job scores 0 against its own history.
            assertEquals(1.0, SimilarityEstimator.jaccard(Set.of(), Set.of()), TOLERANCE);
        }

        @Test
        @DisplayName("one empty set against a populated one scores 0")
        void oneEmptyIsNotAMatch() {
            assertEquals(0.0, SimilarityEstimator.jaccard(Set.of(), Set.of("a")), TOLERANCE);
            assertEquals(0.0, SimilarityEstimator.jaccard(Set.of("a"), Set.of()), TOLERANCE);
        }
    }

    @Nested
    @DisplayName("name tokenisation")
    class Tokenisation {

        @Test
        @DisplayName("splits on hyphen, underscore, whitespace and slash, and lowercases")
        void splitsAndLowercases() {
            assertEquals(Set.of("build", "payment", "service"), BuildRecord.tokenize("Build-Payment_Service"));
            assertEquals(Set.of("folder", "job"), BuildRecord.tokenize("folder/job"));
            assertEquals(Set.of("a", "b"), BuildRecord.tokenize("a   b"));
        }

        @Test
        @DisplayName("a blank or null name yields no tokens")
        void blankNames() {
            assertTrue(BuildRecord.tokenize(null).isEmpty());
            assertTrue(BuildRecord.tokenize("").isEmpty());
            assertTrue(BuildRecord.tokenize("   ").isEmpty());
        }

        @Test
        @DisplayName("repeated separators do not produce empty tokens")
        void repeatedSeparators() {
            assertEquals(Set.of("a", "b"), BuildRecord.tokenize("a--__b"));
        }
    }

    @Nested
    @DisplayName("the similarity formula")
    class Formula {

        @Test
        @DisplayName("weights name 0.5, parameters 0.3 and label 0.2")
        void weightsMatchTheReport() {
            BuildRecord a = BuildRecord.of("build-api", Map.of("BRANCH", "main"), "linux", 0, 0);

            // Everything matches.
            assertEquals(1.0, SimilarityEstimator.similarity(a, a), TOLERANCE);

            // Same name and parameters, different label: loses exactly the 0.2 label term.
            BuildRecord otherLabel = BuildRecord.of("build-api", Map.of("BRANCH", "main"), "windows", 0, 0);
            assertEquals(0.8, SimilarityEstimator.similarity(a, otherLabel), TOLERANCE);

            // Same name and label, different parameter value: loses the 0.3 parameter term.
            BuildRecord otherParams = BuildRecord.of("build-api", Map.of("BRANCH", "dev"), "linux", 0, 0);
            assertEquals(0.7, SimilarityEstimator.similarity(a, otherParams), TOLERANCE);

            // Nothing in common at all.
            BuildRecord nothing = BuildRecord.of("deploy-web", Map.of("ENV", "prod"), "windows", 0, 0);
            assertEquals(0.0, SimilarityEstimator.similarity(a, nothing), TOLERANCE);
        }

        @Test
        @DisplayName("a job's own history scores 1.0, so it dominates automatically")
        void ownHistoryDominates() {
            // The report relies on this: when a job has run before, no special case is needed for
            // "use my own builds", because identical names already score highest.
            BuildRecord self = target("build-payment-service");
            BuildRecord own = history("build-payment-service", "linux", 10 * SECOND, 0);
            BuildRecord sibling = history("build-auth-service", "linux", 60 * SECOND, 0);

            assertTrue(SimilarityEstimator.similarity(self, own) > SimilarityEstimator.similarity(self, sibling));
        }
    }

    @Nested
    @DisplayName("threshold and top-k")
    class Selection {

        @Test
        @DisplayName("a build below the threshold is excluded")
        void belowThresholdIsExcluded() {
            // Nothing in common: no shared name token, a different agent label, and parameters on
            // one side only. 0.5*0 + 0.3*0 + 0.2*0 = 0, well under the 0.35 threshold.
            BuildRecord unrelated =
                    BuildRecord.of("completely-different-thing", Map.of("ENV", "prod"), "windows", 99 * SECOND, 0);

            assertEquals(
                    OptionalLong.empty(),
                    SimilarityEstimator.withReportDefaults()
                            .estimate(target("build-payment-service"), List.of(unrelated)),
                    "a build that clears nothing must not contribute an estimate");
        }

        @Test
        @DisplayName("the threshold filters weakly when jobs share a label and take no parameters")
        void thresholdIsWeakOnHomogeneousInstances() {
            // A consequence of the specified formula that is worth pinning down, because it is
            // surprising and it shapes the experiment.
            //
            // BUILD_PROMPT 4.3.5 fixes the weights at 0.5 name, 0.3 parameters, 0.2 label. Two
            // builds that both take no parameters have identical (empty) parameter sets, so the
            // parameter term contributes its full 0.3, and a shared agent label adds 0.2. That is
            // 0.5 before the name is even considered, which clears the 0.35 threshold on its own.
            //
            // So on a homogeneous controller -- every job unparameterised, one label, which is
            // precisely the experiment's workload -- the threshold excludes almost nothing and the
            // name similarity acts as a ranking weight rather than a filter. The report's cold-start
            // path, where a brand new job finds nothing similar and returns UNKNOWN, will rarely be
            // reached there. Recorded in docs/decisions.md D-016.
            BuildRecord differentName = history("nothing-alike-at-all", "linux", 42 * SECOND, 0);

            assertEquals(
                    0.5,
                    SimilarityEstimator.similarity(target("build-payment-service"), differentName),
                    TOLERANCE,
                    "0.3 from two empty parameter sets plus 0.2 from the matching label");
            assertEquals(
                    42 * SECOND,
                    SimilarityEstimator.withReportDefaults()
                            .estimate(target("build-payment-service"), List.of(differentName))
                            .orElseThrow(),
                    "it clears the threshold, so it is the only candidate and supplies the estimate");
        }

        @Test
        @DisplayName("a closer match still outweighs a weak one that cleared the threshold")
        void closerMatchesDominate() {
            // Which is why the weak filtering above is tolerable rather than harmful: the exact
            // name match scores 1.0 against the weak candidate's 0.5, so it dominates the weighted
            // mean even though both are candidates.
            List<BuildRecord> history = List.of(
                    history("build-payment-service", "linux", 10 * SECOND, 0),
                    history("nothing-alike-at-all", "linux", 100 * SECOND, 0));

            long estimate = SimilarityEstimator.withReportDefaults()
                    .estimate(target("build-payment-service"), history)
                    .orElseThrow();

            assertTrue(
                    estimate < 45 * SECOND,
                    "the exact match must pull the estimate toward 10s, got " + estimate + "ms");
        }

        @Test
        @DisplayName("only the k most similar builds are used")
        void topKOnly() {
            // k = 2 here. Two exact-name matches at 10s, plus three weaker siblings at 100s. With
            // k = 2 only the exact matches count, so the estimate is 10s rather than a blend.
            SimilarityEstimator estimator = new SimilarityEstimator(2, 0.35, 0.0);
            List<BuildRecord> history = List.of(
                    history("build-payment-service", "linux", 10 * SECOND, 0),
                    history("build-payment-service", "linux", 10 * SECOND, 0),
                    history("build-payment-api", "linux", 100 * SECOND, 0),
                    history("build-payment-worker", "linux", 100 * SECOND, 0),
                    history("build-payment-batch", "linux", 100 * SECOND, 0));

            assertEquals(
                    10 * SECOND,
                    estimator.estimate(target("build-payment-service"), history).orElseThrow(),
                    "the weaker siblings must be excluded by k");
        }

        @Test
        @DisplayName("equal similarity and no decay gives the arithmetic mean")
        void equalWeightsGiveTheMean() {
            // Both candidates match exactly and are equally fresh, so their weights are equal and
            // the weighted mean reduces to the arithmetic mean. An exact value, no floating-point
            // guesswork, and it still pins the weighting.
            SimilarityEstimator estimator = new SimilarityEstimator(5, 0.35, 0.1);
            List<BuildRecord> history = List.of(
                    history("build-api", "linux", 10 * SECOND, 0), history("build-api", "linux", 20 * SECOND, 0));

            assertEquals(
                    15 * SECOND,
                    estimator.estimate(target("build-api"), history).orElseThrow());
        }
    }

    @Nested
    @DisplayName("recency decay")
    class Decay {

        @Test
        @DisplayName("an older build influences the estimate less than a recent one")
        void olderBuildsWeighLess() {
            // Same two durations as the mean test above, but the 20s build is ten days old. The
            // estimate must fall below the 15s midpoint, toward the fresher 10s build.
            SimilarityEstimator estimator = new SimilarityEstimator(5, 0.35, 0.1);
            List<BuildRecord> history = List.of(
                    history("build-api", "linux", 10 * SECOND, 0), history("build-api", "linux", 20 * SECOND, 10));

            long estimate = estimator.estimate(target("build-api"), history).orElseThrow();

            assertTrue(
                    estimate > 10 * SECOND && estimate < 15 * SECOND,
                    "expected a value between 10s and the 15s midpoint, got " + estimate + "ms");
        }

        @Test
        @DisplayName("lambda 0 disables decay entirely")
        void zeroLambdaDisablesDecay() {
            // The report's ablation needs this to be configuration rather than a constant.
            SimilarityEstimator noDecay = new SimilarityEstimator(5, 0.35, 0.0);
            List<BuildRecord> history = List.of(
                    history("build-api", "linux", 10 * SECOND, 0), history("build-api", "linux", 20 * SECOND, 365));

            assertEquals(
                    15 * SECOND,
                    noDecay.estimate(target("build-api"), history).orElseThrow(),
                    "with no decay a year-old build counts as much as today's");
        }

        @Test
        @DisplayName("a very old build does not produce a nonsensical estimate")
        void veryOldBuildsStayFinite() {
            // exp(-0.1 * 10000) underflows to 0. If every candidate decays to nothing there is no
            // honest estimate to give, and dividing by a zero weight would produce NaN.
            SimilarityEstimator estimator = SimilarityEstimator.withReportDefaults();
            List<BuildRecord> ancient = List.of(history("build-api", "linux", 10 * SECOND, 10_000));

            OptionalLong estimate = estimator.estimate(target("build-api"), ancient);

            if (estimate.isPresent()) {
                assertTrue(estimate.getAsLong() > 0, "an estimate must be positive, not NaN or zero");
            }
            // Either answer is defensible; producing NaN is not, and that is what is asserted.
        }
    }

    @Nested
    @DisplayName("UNKNOWN")
    class Unknown {

        @Test
        @DisplayName("empty history gives UNKNOWN")
        void emptyHistory() {
            assertEquals(
                    OptionalLong.empty(),
                    SimilarityEstimator.withReportDefaults().estimate(target("anything"), List.of()));
        }

        @Test
        @DisplayName("null history gives UNKNOWN rather than throwing")
        void nullHistory() {
            assertEquals(
                    OptionalLong.empty(),
                    SimilarityEstimator.withReportDefaults().estimate(target("anything"), null));
        }

        @Test
        @DisplayName("a brand new job with no similar history gives UNKNOWN")
        void coldStart() {
            // The cold-start path the report calls out: the scorer maps UNKNOWN to the neutral 0.5
            // so a new job is neither punished nor favoured.
            //
            // Note what it takes to reach this path: the history must differ in agent label too.
            // A differing label costs 0.2 and brings the total to 0.3, just under the threshold.
            // Had these builds shared the target's label they would have scored 0.5 and supplied an
            // estimate, for the reason set out in thresholdIsWeakOnHomogeneousInstances above.
            List<BuildRecord> unrelated = List.of(
                    history("totally-unrelated-alpha", "windows", 10 * SECOND, 0),
                    history("totally-unrelated-beta", "windows", 20 * SECOND, 0));

            assertEquals(
                    0.3,
                    SimilarityEstimator.similarity(target("brand-new-job"), unrelated.get(0)),
                    TOLERANCE,
                    "0.3 from the empty parameter sets, nothing from the name or the label");
            assertEquals(
                    OptionalLong.empty(),
                    SimilarityEstimator.withReportDefaults().estimate(target("brand-new-job"), unrelated));
        }
    }

    @Test
    @DisplayName("parameter signatures distinguish name from value")
    void parameterSignatures() {
        assertEquals(Set.of("BRANCH=main"), BuildRecord.signatures(Map.of("BRANCH", "main")));
        assertTrue(BuildRecord.signatures(Map.of()).isEmpty());
        assertTrue(BuildRecord.signatures(null).isEmpty());

        // Same parameter name, different value, must not look identical.
        assertEquals(
                0.0,
                SimilarityEstimator.jaccard(
                        BuildRecord.signatures(Map.of("BRANCH", "main")),
                        BuildRecord.signatures(Map.of("BRANCH", "dev"))),
                TOLERANCE);
    }
}
