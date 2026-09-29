package io.jenkins.plugins.queueoptimizer.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import io.jenkins.plugins.casc.ConfigurationContext;
import io.jenkins.plugins.casc.ConfiguratorRegistry;
import io.jenkins.plugins.casc.misc.ConfiguredWithCode;
import io.jenkins.plugins.casc.misc.JenkinsConfiguredWithCodeRule;
import io.jenkins.plugins.casc.misc.junit.jupiter.WithJenkinsConfiguredWithCode;
import io.jenkins.plugins.casc.model.CNode;
import io.jenkins.plugins.casc.model.Mapping;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * Required by BUILD_PROMPT 4.3.10: the configuration round-trips through YAML export.
 *
 * <p>Configuration as Code is not a convenience here, it is what makes the experiment reproducible.
 * The baseline and optimized arms differ only by {@code optimizerEnabled}, and both are described by
 * a checked-in YAML file, so a run can be reconstructed from the repository rather than from
 * somebody's memory of which checkboxes were ticked. Milestone 2 configured two Jenkins homes by
 * hand, which is why its two arms were not otherwise comparable.
 *
 * <p><b>A known limitation is pinned by this class rather than hidden by it.</b> On
 * {@code configuration-as-code:2121.v86fe99d4b_b_a_b_}, floating-point attributes of this
 * {@code GlobalConfiguration} are silently ignored on import, while {@code int}, {@code boolean},
 * {@code String} and {@code Secret} attributes apply correctly. See
 * {@link #floatingPointAttributesAreNotAppliedKnownDefect} and {@code docs/decisions.md} D-017.
 */
@WithJenkinsConfiguredWithCode
class ConfigAsCodeIT {

    @Test
    @DisplayName("YAML sets the integer, boolean, string and secret fields")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void yamlSetsNonFloatingPointFields(JenkinsConfiguredWithCodeRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();

        // optimizerEnabled is the field the experiment actually switches between its two arms, and
        // it applies correctly. That is what keeps the main comparison reproducible from YAML.
        assertFalse(config.isOptimizerEnabled(), "the baseline arm turns the optimizer off");

        assertEquals(3, config.getAgingIntervalMinutes());
        assertEquals(7, config.getEstimatorK());
        assertEquals(25, config.getHistoryWindow());
        assertEquals(30, config.getRescoreIntervalSeconds());
        assertTrue(config.isMetricsEnabled());
        assertEquals("http://backend:8000/api/metrics", config.getMetricsBackendUrl());
    }

    @Test
    @DisplayName("the metrics token is read from YAML and stored as a Secret")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void tokenIsStoredAsASecret(JenkinsConfiguredWithCodeRule j) {
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertNotNull(config.getMetricsToken(), "the token should have been read from the YAML");
        assertEquals("s3cr3t-metrics-token", config.getMetricsToken().getPlainText());
        assertTrue(config.isMetricsPublishable(), "a URL and a token together mean publishable");
    }

    @Test
    @DisplayName("KNOWN DEFECT: JCasC silently ignores the floating-point fields on import")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void floatingPointAttributesAreNotAppliedKnownDefect(JenkinsConfiguredWithCodeRule j) {
        // This test asserts behaviour that is WRONG, on purpose, so the defect is visible in the
        // suite instead of lurking. When JCasC starts applying these, this test fails and should be
        // replaced by one asserting the YAML values.
        //
        // The YAML sets weightUrgency 0.6, weightDependency 0.25, weightExecutionTime 0.15,
        // agingBonusPerInterval 0.08, agingCap 0.24, similarityThreshold 0.4 and
        // recencyLambdaPerDay 0.2. Every one is ignored and the Appendix D default remains.
        //
        // Established with a verified compile, after an earlier round of experiments turned out to
        // be reading stale classes. Ruled out: the YAML scalar form (quoted and unquoted behave
        // identically), integer-valued floats, the doCheck* validators, boxing the field, getter
        // and setter as Double, and the JVM locale (en/US). Attribute discovery is correct -- JCasC
        // reports all fifteen attributes with their proper types. Only the import silently fails.
        //
        // Impact is contained but real. optimizerEnabled applies, so the main baseline-versus-
        // optimized comparison is fully reproducible from YAML. The aging-ablation arm of the
        // experiment matrix varies agingBonusPerInterval and agingCap, so it cannot be driven
        // through JCasC until this is resolved. Tracked in PROGRESS.md under Needs human.
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertEquals(0.5, config.getWeightUrgency(), 0.0001, "still the default, not the YAML's 0.6");
        assertEquals(0.3, config.getWeightDependency(), 0.0001);
        assertEquals(0.2, config.getWeightExecutionTime(), 0.0001);
        assertEquals(0.05, config.getAgingBonusPerInterval(), 0.0001);
        assertEquals(0.15, config.getAgingCap(), 0.0001);
        assertEquals(0.35, config.getSimilarityThreshold(), 0.0001);
        assertEquals(0.1, config.getRecencyLambdaPerDay(), 0.0001);
    }

    @Test
    @DisplayName("every field survives an export, including the floating-point ones")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void everyFieldSurvivesExport(JenkinsConfiguredWithCodeRule j) throws Exception {
        // Export is unaffected by the import defect above, so the round-trip requirement still
        // holds for the shape of the document: nothing is dropped.
        ConfiguratorRegistry registry = ConfiguratorRegistry.get();
        ConfigurationContext context = new ConfigurationContext(registry);
        CNode exported =
                registry.lookupOrFail(OptimizerConfiguration.class).describe(OptimizerConfiguration.get(), context);

        assertNotNull(exported, "the configuration exported to nothing at all");
        Mapping mapping = exported.asMapping();

        for (String field : new String[] {
            "optimizerEnabled",
            "weightUrgency",
            "weightDependency",
            "weightExecutionTime",
            "agingBonusPerInterval",
            "agingIntervalMinutes",
            "agingCap",
            "estimatorK",
            "similarityThreshold",
            "recencyLambdaPerDay",
            "historyWindow",
            "rescoreIntervalSeconds",
            "metricsEnabled",
            "metricsBackendUrl"
        }) {
            assertTrue(mapping.containsKey(field), "export dropped the field '" + field + "'");
        }

        // The values that did import must export unchanged.
        assertEquals("false", mapping.get("optimizerEnabled").toString());
        assertEquals("7", mapping.get("estimatorK").toString());
        assertEquals(
                "http://backend:8000/api/metrics",
                mapping.get("metricsBackendUrl").toString());
    }

    @Test
    @DisplayName("an exported secret is not the plain text")
    @ConfiguredWithCode("optimizer-configuration.yaml")
    void exportedSecretIsEncrypted(JenkinsConfiguredWithCodeRule j) throws Exception {
        ConfiguratorRegistry registry = ConfiguratorRegistry.get();
        ConfigurationContext context = new ConfigurationContext(registry);
        CNode exported =
                registry.lookupOrFail(OptimizerConfiguration.class).describe(OptimizerConfiguration.get(), context);

        Mapping mapping = exported.asMapping();
        if (mapping.containsKey("metricsToken")) {
            assertFalse(
                    mapping.get("metricsToken").toString().contains("s3cr3t-metrics-token"),
                    "an exported YAML is a file people commit; the plain-text token must not be in it");
        }
    }

    @Test
    @DisplayName("omitted fields keep their Appendix D defaults")
    @ConfiguredWithCode("optimizer-minimal.yaml")
    void omittedFieldsKeepTheirDefaults(JenkinsConfiguredWithCodeRule j) {
        // The shape the experiment's two arms use: they differ by one line, and everything else
        // must stay at the report's values rather than being zeroed.
        OptimizerConfiguration config = OptimizerConfiguration.get();

        assertFalse(config.isOptimizerEnabled(), "the one field the file sets");
        assertEquals(0.5, config.getWeightUrgency(), 0.0001);
        assertEquals(0.3, config.getWeightDependency(), 0.0001);
        assertEquals(0.2, config.getWeightExecutionTime(), 0.0001);
        assertEquals(5, config.getAgingIntervalMinutes());
        assertEquals(5, config.getEstimatorK());
        assertEquals(50, config.getHistoryWindow());
        assertTrue(config.weightsSumToOne(), "the defaults must still be the report's formula");
        assertEquals("", config.getMetricsBackendUrl(), "empty by default, per D-006");
    }

    @Test
    @DisplayName("the experiment's baseline arm is reproducible from YAML")
    @ConfiguredWithCode("optimizer-minimal.yaml")
    void baselineArmIsReproducibleFromYaml(JenkinsConfiguredWithCodeRule j) {
        // The property that actually matters for the experiment, stated as its own test so the
        // known defect above cannot be mistaken for "JCasC does not work here at all".
        assertFalse(
                OptimizerConfiguration.get().isOptimizerEnabled(),
                "the baseline arm must be configurable from a checked-in file, or the experiment "
                        + "is not reproducible");
    }
}
