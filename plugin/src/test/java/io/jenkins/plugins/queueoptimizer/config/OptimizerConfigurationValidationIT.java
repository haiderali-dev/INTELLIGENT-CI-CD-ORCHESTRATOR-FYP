package io.jenkins.plugins.queueoptimizer.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import hudson.util.FormValidation;
import hudson.util.FormValidation.Kind;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.DoubleFunction;
import java.util.function.IntFunction;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.jvnet.hudson.test.JenkinsRule;
import org.jvnet.hudson.test.junit.jupiter.WithJenkins;

/**
 * The global configuration form's validation, by equivalence partitioning and boundary values.
 *
 * <p>Each setting is tried just below, on and just above the edge of its valid range. Coverage
 * showed none of these checks had ever run in a test (2026-10-20); they are what stands between a
 * typing slip on the configuration page and, for example, an aging interval of 0.
 */
@WithJenkins
class OptimizerConfigurationValidationIT {

    private static void assertKinds(String setting, Map<Object, Kind> expected, Map<Object, FormValidation> actual) {
        for (Map.Entry<Object, Kind> entry : expected.entrySet()) {
            assertEquals(
                    entry.getValue(),
                    actual.get(entry.getKey()).kind,
                    setting + " = " + entry.getKey() + ": "
                            + actual.get(entry.getKey()).getMessage());
        }
    }

    @Test
    @DisplayName("the whole-number settings refuse 0 and accept 1, the edge of their range")
    void wholeNumberSettingsStartAtOne(JenkinsRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();
        Map<String, IntFunction<FormValidation>> checks = new LinkedHashMap<>();
        checks.put("agingIntervalMinutes", config::doCheckAgingIntervalMinutes);
        checks.put("estimatorK", config::doCheckEstimatorK);
        checks.put("historyWindow", config::doCheckHistoryWindow);
        checks.put("rescoreIntervalSeconds", config::doCheckRescoreIntervalSeconds);

        for (Map.Entry<String, IntFunction<FormValidation>> check : checks.entrySet()) {
            Map<Object, FormValidation> actual = new LinkedHashMap<>();
            for (int value : new int[] {-1, 0, 1, 2, 1000}) {
                actual.put(value, check.getValue().apply(value));
            }
            assertKinds(
                    check.getKey(),
                    Map.of(-1, Kind.ERROR, 0, Kind.ERROR, 1, Kind.OK, 2, Kind.OK, 1000, Kind.OK),
                    actual);
        }
    }

    @Test
    @DisplayName("the similarity threshold is a fraction: 0 and 1 are in, just outside them is out")
    void similarityThresholdIsAFraction(JenkinsRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();
        Map<Object, FormValidation> actual = new LinkedHashMap<>();
        for (double value : new double[] {-0.01, 0.0, 0.35, 1.0, 1.01}) {
            actual.put(value, config.doCheckSimilarityThreshold(value));
        }

        assertKinds(
                "similarityThreshold",
                Map.of(-0.01, Kind.ERROR, 0.0, Kind.OK, 0.35, Kind.OK, 1.0, Kind.OK, 1.01, Kind.ERROR),
                actual);
    }

    @Test
    @DisplayName("the bonus, its cap and the recency decay cannot be negative, and zero is allowed")
    void nonNegativeSettings(JenkinsRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();
        Map<String, DoubleFunction<FormValidation>> checks = new LinkedHashMap<>();
        checks.put("agingBonusPerInterval", config::doCheckAgingBonusPerInterval);
        checks.put("agingCap", config::doCheckAgingCap);
        checks.put("recencyLambdaPerDay", config::doCheckRecencyLambdaPerDay);

        for (Map.Entry<String, DoubleFunction<FormValidation>> check : checks.entrySet()) {
            Map<Object, FormValidation> actual = new LinkedHashMap<>();
            for (double value : new double[] {-0.001, 0.0, 0.05}) {
                actual.put(value, check.getValue().apply(value));
            }
            assertKinds(check.getKey(), Map.of(-0.001, Kind.ERROR, 0.0, Kind.OK, 0.05, Kind.OK), actual);
        }
    }

    @Test
    @DisplayName("a negative weight is refused, and weights that do not sum to 1 only warn")
    void weightsAreCheckedSinglyAndTogether(JenkinsRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertEquals(Kind.ERROR, config.doCheckWeightUrgency(-0.1, 0.3, 0.2).kind);
        assertEquals(Kind.OK, config.doCheckWeightDependency(0.3, 0.5, 0.2).kind, "the report's weights sum to 1");

        // An experiment may set other weights deliberately, so it is a warning, not a refusal.
        FormValidation summed = config.doCheckWeightExecutionTime(0.2, 0.6, 0.3);
        assertEquals(Kind.WARNING, summed.kind);
        assertTrue(summed.getMessage().contains("1.100"), summed.getMessage());
    }

    @Test
    @DisplayName("the weight warning follows the values on the form, not the last save")
    void theWeightWarningFollowsTheForm(JenkinsRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();

        // Saved weights summing to 1.1 must not warn about a form that sums to 1, and saved
        // weights summing to 1 must not hide a form that sums to 1.1. Until D-072 the check summed
        // the saved weights, so both of these were wrong.
        config.setWeightUrgency(0.6);
        assertEquals(Kind.OK, config.doCheckWeightUrgency(0.5, 0.3, 0.2).kind);
        config.setWeightUrgency(0.5);
        assertEquals(Kind.WARNING, config.doCheckWeightUrgency(0.6, 0.3, 0.2).kind);
    }
}
